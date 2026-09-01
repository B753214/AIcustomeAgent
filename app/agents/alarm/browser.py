"""Playwright 登录 info-plate 并拉取监控数据（对齐 fc_monitor.js fetchPageData）。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import PROJECT_ROOT, settings

_INFO_PLATE_BASE = (settings.alarm_info_plate_base_url or "https://info-plate.fc.alibaba-inc.com").rstrip("/")
_API_BASE = f"{_INFO_PLATE_BASE}/api"

_DETAIL_COLUMNS = [
    "id", "time", "adiu", "diu", "upload_time", "ajx_ver", "tag", "sub_tag",
    "scene", "operate_msg", "page_name", "order_id", "bundle_name", "env",
    "content", "eagleeye_trace_id", "uid", "div1", "err_flag", "err_msg", "url",
]

_playwright = None
_context = None
_page: Any | None = None
_logged_in = False
_lock = asyncio.Lock()


def _profile_dir() -> Path:
    raw = settings.alarm_browser_profile_dir or ".browser_profile"
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _to_date_str(ts: str | int | None) -> str | None:
    if ts is None or ts == "":
        return None
    try:
        d = datetime.fromtimestamp(int(ts) / 1000)
    except (TypeError, ValueError, OSError):
        return None
    return d.strftime("%Y-%m-%d %H:%M:%S")


async def _ensure_playwright():
    global _playwright, _context, _page
    if _page is not None:
        return
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "未安装 playwright。请执行: pip install playwright && playwright install chromium"
        ) from e

    _playwright = await async_playwright().start()
    timeout_ms = max(30_000, settings.alarm_browser_timeout_sec * 1000)
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=str(_profile_dir()),
        headless=settings.alarm_browser_headless,
        ignore_https_errors=True,
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--ignore-certificate-errors",
        ],
        timeout=timeout_ms,
    )
    _page = _context.pages[0] if _context.pages else await _context.new_page()
    print("[BROWSER] Playwright 已启动")


async def close_browser() -> None:
    """关闭浏览器（测试 / 关机用）。"""
    global _playwright, _context, _page, _logged_in
    async with _lock:
        if _context is not None:
            try:
                await _context.close()
            except Exception as e:
                print(f"[BROWSER] 关闭异常: {e}")
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
        _playwright = None
        _context = None
        _page = None
        _logged_in = False


async def ensure_logged_in() -> bool:
    """未登录则尝试账号密码登录；SMS/扫码场景返回 False（Day11 再补 /sms）。"""
    global _logged_in
    async with _lock:
        return await _ensure_logged_in_unlocked()


async def _ensure_logged_in_unlocked() -> bool:
    global _logged_in
    if not settings.alarm_browser_enabled:
        return False
    if _logged_in and _page is not None:
        return True

    user = (settings.alarm_info_plate_user or "").strip()
    password = (settings.alarm_info_plate_password or "").strip()
    if not user or not password:
        print("[BROWSER] 未配置 ALARM_INFO_PLATE_USER / ALARM_INFO_PLATE_PASSWORD")
        return False

    try:
        await _ensure_playwright()
        assert _page is not None
        page = _page
        timeout_ms = settings.alarm_browser_timeout_sec * 1000

        print("[LOGIN] 开始登录...")
        await page.goto(
            f"{_INFO_PLATE_BASE}/monitor/searchall?bizType=30",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        await page.wait_for_timeout(1500)
        current = page.url
        print(f"[LOGIN] 当前页面: {current}")

        if "login" not in current.lower():
            print("[LOGIN] 已登录（profile 复用）")
            _logged_in = True
            return True

        account = await page.query_selector("input#account")
        if account is None:
            print("[LOGIN] 检测到登录页面，但未找到账号输入框，登录流程异常")
            _logged_in = False
            return False
        if account:
            await page.fill("input#account", user)
            await page.fill("input#password", password)
            await page.wait_for_timeout(400)
            submit = await page.query_selector('button[type="submit"]')
            if submit:
                await submit.click()
            else:
                await page.keyboard.press("Enter")
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)

        page_text = await page.evaluate("() => document.body.innerText")
        if any(x in page_text for x in ("select an identity", "选择身份", "选择一个身份")):
            print(f"[LOGIN] 身份选择页面，选择: {user}")
            await page.evaluate(
                """(username) => {
                    const items = document.querySelectorAll('div, span, li, a, label, p');
                    for (const item of items) {
                        if (item.textContent.includes(username) && item.textContent.length < 200) {
                            item.click(); return;
                        }
                    }
                    const radios = document.querySelectorAll(
                        'input[type="radio"], .ant-radio-wrapper, [role="radio"]'
                    );
                    if (radios.length > 0) { radios[0].click(); return; }
                    const cards = document.querySelectorAll(
                        '.identity-card, .account-item, [class*="identity"], [class*="account"]'
                    );
                    if (cards.length > 0) cards[0].click();
                }""",
                user,
            )
            await page.wait_for_timeout(800)
            await page.evaluate(
                """() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const t = btn.textContent || '';
                        if (t.includes('Submit') || t.includes('提交') || t.includes('登录')
                            || t.includes('确定') || t.includes('下一步')) {
                            btn.click(); return;
                        }
                    }
                }"""
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            page_text = await page.evaluate("() => document.body.innerText")

        if "SMS" in page_text or "短信验证" in page_text:
            print("[LOGIN] 需要短信验证码（Day8 未接 /sms，返回失败）")
            _logged_in = False
            return False

        if "QR code" in page_text or "扫码" in page_text:
            print("[LOGIN] 需要扫码验证（Day8 不阻塞等待，返回失败）")
            _logged_in = False
            return False

        final = page.url
        print(f"[LOGIN] 登录后页面: {final}")
        host = urlparse(final).hostname or ""
        if "info-plate" in host:
            _logged_in = True
            print("[LOGIN] 登录成功")
            return True

        print("[LOGIN] 登录失败")
        _logged_in = False
        return False
    except Exception as e:
        print(f"[LOGIN] 登录异常: {e}")
        _logged_in = False
        return False


async def fetch_via_browser(
    *,
    raw_url: str,
    market_config_id: str,
    biz_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict | None:
    """成功返回 {channel, monitorRate, monitorDetail, marketConfig, page, pageSize, pagination}；失败 None。"""
    if not settings.alarm_browser_enabled:
        return None
    if not (raw_url or "").strip() or not market_config_id:
        return None

    page_no = max(1, int(page or 1))
    size = max(1, int(page_size or 50))

    async with _lock:
        try:
            ok = await _ensure_logged_in_unlocked()
            if not ok:
                print("[BROWSER] 登录失败，跳过浏览器拉数")
                return None

            assert _page is not None
            page = _page  # Playwright Page；分页用 page_no / size
            timeout_ms = settings.alarm_browser_timeout_sec * 1000

            # 保证在 info-plate 域（cookie）
            try:
                host = urlparse(page.url).hostname or ""
            except Exception:
                host = ""
            if "info-plate" not in host:
                await page.goto(
                    f"{_INFO_PLATE_BASE}/monitor/searchall?bizType={biz_type or '30'}",
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                if "login" in page.url.lower():
                    global _logged_in
                    _logged_in = False
                    if not await _ensure_logged_in_unlocked():
                        return None

            qs_start = start_time
            qs_end = end_time
            if not qs_start or not qs_end:
                try:
                    from urllib.parse import parse_qs, urlparse as up

                    q = parse_qs(up(raw_url).query)
                    qs_start = qs_start or (q.get("startTime") or [None])[0]
                    qs_end = qs_end or (q.get("endTime") or [None])[0]
                except Exception:
                    pass

            ts = int(datetime.now().timestamp() * 1000)
            rate_url = (
                f"{_API_BASE}/monitor/getMonitorRate"
                f"?id={market_config_id}&startTime={qs_start or ''}"
                f"&endTime={qs_end or ''}&_={ts}"
            )
            print("[BROWSER] getMonitorRate...")
            rate_json = await page.evaluate(
                """async (url) => {
                    const resp = await fetch(url);
                    return await resp.json();
                }""",
                rate_url,
            )
            rate_data = (rate_json or {}).get("data")
            if not rate_data:
                print(f"[BROWSER] getMonitorRate 无 data: {str(rate_json)[:200]}")
                return None

            market_config: Any = None
            try:
                cfg_url = (
                    f"{_API_BASE}/monitor/queryBusinessMarketConfig"
                    f"?id={market_config_id}&_={ts + 1}"
                )
                cfg_json = await page.evaluate(
                    """async (url) => {
                        const resp = await fetch(url);
                        return await resp.json();
                    }""",
                    cfg_url,
                )
                config_data = (cfg_json or {}).get("data")
                if isinstance(config_data, dict) and config_data.get("datas") is not None:
                    datas = config_data["datas"]
                    market_config = datas[0] if isinstance(datas, list) and datas else datas
                else:
                    market_config = config_data
            except Exception as e:
                print(f"[BROWSER] marketConfig 失败: {e}")

            detail_data: Any = None
            try:
                conditions: list = []
                table_id = 10026
                if isinstance(market_config, dict):
                    table_id = market_config.get("tableId") or table_id
                    faas_raw = market_config.get("faasParam")
                    if faas_raw:
                        faas = (
                            json.loads(faas_raw)
                            if isinstance(faas_raw, str)
                            else faas_raw
                        )
                        if isinstance(faas, dict):
                            if faas.get("conditions"):
                                conditions = faas["conditions"]
                            elif (faas.get("monitorRate") or {}).get("conditionList"):
                                conditions = faas["monitorRate"]["conditionList"]
                            if faas.get("tableId"):
                                table_id = faas["tableId"]
                            elif (faas.get("monitorRate") or {}).get("tableId"):
                                table_id = faas["monitorRate"]["tableId"]

                start_str = _to_date_str(qs_start) or ""
                end_str = _to_date_str(qs_end) or ""
                detail_body = {
                    "columns": _DETAIL_COLUMNS,
                    "where": [
                        {
                            "column": "time",
                            "type": "str",
                            "condition": [start_str, end_str],
                        }
                    ],
                    "conditions": conditions,
                    "tableId": table_id,
                    "orderByKey": "time",
                    "page": page_no,
                    "pageSize": size,
                }
                detail_url = f"{_API_BASE}/ability/monitorDetail?_={ts + 2}"
                detail_json = await page.evaluate(
                    """async ({ url, body }) => {
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(body),
                        });
                        return await resp.json();
                    }""",
                    {"url": detail_url, "body": detail_body},
                )
                detail_data = (detail_json or {}).get("data")
                if isinstance(detail_data, list):
                    items = len(detail_data)
                elif isinstance(detail_data, dict):
                    items = len(detail_data.get("list") or [])
                else:
                    items = 0
                print(f"[BROWSER] monitorDetail: {items} 条")
            except Exception as e:
                print(f"[BROWSER] monitorDetail 失败: {e}")

            return {
                "channel": "browser",
                "monitorRate": rate_data,
                "monitorDetail": detail_data,
                "marketConfig": market_config or {},
                "page": page_no,
                "pageSize": size,
                "pagination": "browser",
            }
        except Exception as e:
            print(f"[BROWSER] fetch failed: {e}")
            return None