"""告警 Agent：自主 Plan & Execute 测试 Demo（不影响现有 pipeline/runner）。

用法（在仓库根目录 AICustomeRobort）::

    # 真调 LLM 规划 + 真执行工具（需 .env / 可选浏览器）
    python -m app.agents.alarm.pe_demo

    # 只看流程：固定计划 + 模拟执行（不调 LLM / 不拉数）
    python -m app.agents.alarm.pe_demo --dry-run

    # LLM 规划，但执行用模拟结果
    python -m app.agents.alarm.pe_demo --dry-exec

调试日志前缀::
    [PE-DEMO] [PLAN] / [EXEC] / [OBS] / [DONE]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings

# ---------- 调试输出 ----------

def _dbg(phase: str, msg: str, **extra: Any) -> None:
    print(f"[PE-DEMO] [{phase}] {msg}")
    if extra:
        for k, v in extra.items():
            text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
            if len(text) > 800:
                text = text[:800] + "…(truncated)"
            print(f"         {k}: {text}")


# ---------- 工具目录（Planner 只能选这些 id）----------

TOOL_CATALOG = [
    {
        "id": "parse",
        "desc": "解析告警正文/URL，得到 configId、指标名、时间范围等",
    },
    {
        "id": "classify",
        "desc": "根据指标名或【类型】推断 skill/playbook（ajx/render/bff/voc/precise）",
    },
    {
        "id": "fetch",
        "desc": "拉取监控 rate + detail；可选参数 page（默认 1）",
        "params": {"page": "int, 可选, 默认1"},
    },
    {
        "id": "analyze_detail",
        "desc": "对已拉取的明细做聚合分析（topErrors、uniqueUsers 等）",
    },
    {
        "id": "switch_playbook",
        "desc": "更换排查 playbook；参数 key=ajx|render|bff|voc|precise",
        "params": {"key": "string, 必填"},
    },
    {
        "id": "report",
        "desc": "基于当前 state 用 playbook + LLM 生成排查报告（终态）",
    },
    {
        "id": "finish",
        "desc": "结束（已有足够结论或无法继续）",
    },
]

ALLOWED_IDS = {t["id"] for t in TOOL_CATALOG}


# ---------- Planner ----------

_PLANNER_SYSTEM = """你是告警排查的 Plan 规划器。
只能从给定工具目录中选择步骤，按数组顺序规划执行。
禁止发明目录外的工具。禁止输出 markdown。
只输出一个 JSON 对象，格式严格如下：
{"steps":[{"id":"parse"},{"id":"classify"},{"id":"fetch","page":1},{"id":"analyze_detail"},{"id":"report"}],"rationale":"一句话原因"}
"""


def _build_llm():
    return init_chat_model(
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        model=settings.AIROBOT_LLM_MODEL,
        model_provider=settings.provider,
    )


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def _validate_plan(plan: dict) -> list[dict]:
    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        return []
    out: list[dict] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if sid not in ALLOWED_IDS:
            _dbg("PLAN", f"丢弃非法步骤 id={sid!r}")
            continue
        item = {"id": sid}
        if sid == "fetch" and s.get("page") is not None:
            try:
                item["page"] = max(1, int(s["page"]))
            except (TypeError, ValueError):
                item["page"] = 1
        if sid == "switch_playbook" and s.get("key"):
            item["key"] = str(s["key"]).strip()
        out.append(item)
    return out


async def make_plan(message: str, *, dry_run: bool = False) -> dict:
    """返回 {steps, rationale, raw}。"""
    if dry_run:
        plan = {
            "steps": [
                {"id": "parse"},
                {"id": "classify"},
                {"id": "fetch", "page": 1},
                {"id": "analyze_detail"},
                {"id": "report"},
            ],
            "rationale": "dry-run 固定计划：解析→分类→拉数→分析→报告",
            "raw": "(dry-run, no LLM)",
        }
        _dbg("PLAN", "使用固定 mock 计划", plan=plan)
        return plan

    catalog_text = json.dumps(TOOL_CATALOG, ensure_ascii=False, indent=2)
    user = f"""告警原文：
{message[:2000]}

工具目录：
{catalog_text}

请输出 JSON 计划。"""
    _dbg("PLAN", "调用 LLM 规划…", catalog_ids=list(ALLOWED_IDS))
    llm = _build_llm()
    resp = await llm.ainvoke(
        [SystemMessage(content=_PLANNER_SYSTEM), HumanMessage(content=user)]
    )
    raw = resp.content if hasattr(resp, "content") else str(resp)
    _dbg("PLAN", "LLM 原始输出", raw=raw)
    parsed = _extract_json(raw if isinstance(raw, str) else str(raw))
    steps = _validate_plan(parsed)
    plan = {
        "steps": steps,
        "rationale": str(parsed.get("rationale") or ""),
        "raw": raw if isinstance(raw, str) else str(raw),
    }
    _dbg("PLAN", "校验后计划", steps=steps, rationale=plan["rationale"])
    return plan


# ---------- State / Executor ----------

def _initial_state(message: str) -> dict:
    return {
        "message": message,
        "parsed": {},
        "skill_key": None,
        "skill_meta": {},
        "config_id": "",
        "biz_type": "30",
        "start_time": None,
        "end_time": None,
        "page": 1,
        "page_size": int(getattr(settings, "alarm_detail_page_size", 20) or 20),
        "fetch_res": None,
        "monitor_rate": {},
        "monitor_detail": None,
        "error_analysis": None,
        "reply": None,
        "exec_log": [],
    }


def _resolve_url_params(parsed: dict, message: str) -> None:
    from app.agents.alarm.parse import extract_monitor_url

    detail_url = parsed.get("detailUrl") or extract_monitor_url(message) or ""
    if detail_url:
        parsed["detailUrl"] = detail_url
    qs = parse_qs(urlparse(detail_url).query) if detail_url else {}
    config_id = (
        parsed.get("configId") or (qs.get("marketConfigId") or [""])[0] or ""
    ).strip()
    if config_id:
        parsed["configId"] = config_id


async def _exec_parse(state: dict, dry_exec: bool) -> str:
    from app.agents.alarm.parse import parse_alarm_message

    if dry_exec:
        state["parsed"] = {
            "indicator": "页面白屏",
            "configId": "11664",
            "detailUrl": (
                "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
                "?marketConfigId=11664&bizType=30"
            ),
            "alarmType": "",
            "hitRule": "失败次数突增",
            "current": 42,
            "yesterdayValue": 15,
        }
        state["config_id"] = "11664"
        state["biz_type"] = "30"
        return "dry-exec: parsed mock alarm (configId=11664)"

    parsed = parse_alarm_message(state["message"])
    _resolve_url_params(parsed, state["message"])
    state["parsed"] = parsed
    state["config_id"] = (parsed.get("configId") or "").strip()
    detail = parsed.get("detailUrl") or ""
    if detail:
        qs = parse_qs(urlparse(detail).query)
        state["biz_type"] = (qs.get("bizType") or ["30"])[0]
        state["start_time"] = (qs.get("startTime") or [None])[0]
        state["end_time"] = (qs.get("endTime") or [None])[0]
    return f"parsed indicator={parsed.get('indicator')!r} configId={state['config_id']!r}"


async def _exec_classify(state: dict, dry_exec: bool) -> str:
    from app.agents.alarm.classify import classify_alarm

    if dry_exec:
        state["skill_key"] = "render"
        state["skill_meta"] = {
            "key": "render",
            "type": "渲染异常",
            "skill": "wuying-render-monitor-troubleshooting",
        }
        return "dry-exec: skill=render"

    cls = classify_alarm(state.get("parsed") or {})
    state["skill_meta"] = cls
    state["skill_key"] = cls.get("key")
    return f"skill_key={state['skill_key']} type={cls.get('type')}"


async def _exec_fetch(state: dict, step: dict, dry_exec: bool) -> str:
    page = int(step.get("page") or 1)
    state["page"] = page
    if dry_exec:
        state["fetch_res"] = {"channel": "dry-exec"}
        state["monitor_rate"] = {
            "name": "下单失败监控",
            "count": 42,
            "yesterdayCount": 15,
            "lastWeekCount": 38,
        }
        state["monitor_detail"] = {
            "list": [
                {
                    "err_msg": "Connection timeout",
                    "url": "/api/order/create",
                    "scene": "提单",
                    "page_name": "下单页",
                    "uid": f"u{i}",
                }
                for i in range(12)
            ]
        }
        return f"dry-exec: fetch page={page} detail=12"

    from app.agents.alarm.fetcher import fetch_monitor_data, merge_monitor_details

    config_id = (state.get("config_id") or "").strip()
    if not config_id:
        return "SKIP fetch: 无 config_id"

    async def _progress(msg: str) -> None:
        _dbg("EXEC", f"fetch progress: {msg}")

    res = await fetch_monitor_data(
        market_config_id=config_id,
        biz_type=state.get("biz_type") or "30",
        start_time=state.get("start_time"),
        end_time=state.get("end_time"),
        raw_url=(state.get("parsed") or {}).get("detailUrl") or "",
        on_progress=_progress,
        page=page,
        page_size=int(state.get("page_size") or 20),
    )
    state["fetch_res"] = res
    if not res:
        return f"fetch page={page} FAILED → None"

    state["monitor_rate"] = dict(res.get("monitorRate") or {})
    detail = res.get("monitorDetail")
    if state.get("monitor_detail") is None:
        state["monitor_detail"] = detail
    else:
        state["monitor_detail"] = merge_monitor_details(state["monitor_detail"], detail)
    n = 0
    if isinstance(detail, dict):
        n = len(detail.get("list") or [])
    elif isinstance(detail, list):
        n = len(detail)
    return f"fetch page={page} channel={res.get('channel')} items={n}"


async def _exec_analyze(state: dict, dry_exec: bool) -> str:
    from app.agents.alarm.report import analyze_error_details

    detail = state.get("monitor_detail")
    if detail is None and dry_exec:
        return "dry-exec: no detail"
    ea = analyze_error_details(detail) if detail is not None else None
    state["error_analysis"] = ea
    if not ea:
        return "analyze: empty"
    return (
        f"analyze total={ea.get('total')} "
        f"uniqueUsers={ea.get('uniqueUsers')} "
        f"top1={(ea.get('topErrorsRaw') or [{}])[0]}"
    )


async def _exec_switch_playbook(state: dict, step: dict, dry_exec: bool) -> str:
    from app.agents.alarm.classify import SKILL_MAP

    key = str(step.get("key") or "").strip()
    if key not in SKILL_MAP:
        return f"SKIP switch_playbook: invalid key={key!r}"
    meta = SKILL_MAP[key]
    state["skill_key"] = key
    state["skill_meta"] = {"key": key, **meta}
    return f"switch_playbook → {key} ({meta.get('type')})" + (" [dry]" if dry_exec else "")


async def _exec_report(state: dict, dry_exec: bool) -> str:
    if dry_exec:
        ea = state.get("error_analysis") or {}
        state["reply"] = (
            "【dry-exec 模拟报告】\n"
            f"skill={state.get('skill_key')}\n"
            f"rate={state.get('monitor_rate')}\n"
            f"analysis_total={ea.get('total')}\n"
            "结论：Demo 未调用真实报告 LLM。"
        )
        return "dry-exec: mock report written"

    from app.agents.alarm.runner import _assemble, _build_llm, _finalize_reply
    from app.services.resilience import ainvoke_with_retry

    parsed = state.get("parsed") or {}
    cls = state.get("skill_meta") or {"key": state.get("skill_key") or "precise"}
    res = None
    if state.get("fetch_res"):
        res = {
            "channel": (state.get("fetch_res") or {}).get("channel") or "text_fallback",
            "monitorRate": state.get("monitor_rate") or {},
            "monitorDetail": state.get("monitor_detail"),
        }
    messages, _sources, _meta, error_analysis = _assemble(
        state["message"], parsed, cls, state.get("config_id") or "", res
    )
    if error_analysis is not None:
        state["error_analysis"] = error_analysis
    _dbg("EXEC", "调用报告 LLM…")
    llm = _build_llm()
    response = await ainvoke_with_retry(llm.ainvoke, messages)
    ai_text = response.content if hasattr(response, "content") else str(response)
    state["reply"] = _finalize_reply(
        ai_text,
        rate=state.get("monitor_rate") or {},
        error_analysis=state.get("error_analysis"),
        monitor_url=parsed.get("detailUrl") or "",
        channel=(state.get("fetch_res") or {}).get("channel") or "text_fallback",
        cls=cls,
    )
    return f"report ok, reply_len={len(state['reply'] or '')}"


async def execute_step(state: dict, step: dict, *, dry_exec: bool) -> None:
    sid = step["id"]
    _dbg("EXEC", f"开始执行步骤 → {sid}", step=step)
    if sid == "parse":
        obs = await _exec_parse(state, dry_exec)
    elif sid == "classify":
        obs = await _exec_classify(state, dry_exec)
    elif sid == "fetch":
        obs = await _exec_fetch(state, step, dry_exec)
    elif sid == "analyze_detail":
        obs = await _exec_analyze(state, dry_exec)
    elif sid == "switch_playbook":
        obs = await _exec_switch_playbook(state, step, dry_exec)
    elif sid == "report":
        obs = await _exec_report(state, dry_exec)
    elif sid == "finish":
        obs = "finish"
    else:
        obs = f"unknown step {sid}"
    state["exec_log"].append({"step": step, "obs": obs})
    _dbg("OBS", obs)


# ---------- 主流程 ----------

async def run_pe_demo(
    message: str,
    *,
    dry_run: bool = False,
    dry_exec: bool = False,
) -> dict:
    """先输出计划，再逐步执行。返回最终 state。"""
    print("=" * 60)
    print("[PE-DEMO] Plan & Execute 测试开始（不影响现有 runner/pipeline）")
    print("=" * 60)
    _dbg("INIT", "输入告警摘要", message=message[:300])

    # 1) Plan
    print("\n>>> PHASE 1: PLAN\n")
    plan = await make_plan(message, dry_run=dry_run)
    steps = plan.get("steps") or []
    if not steps:
        _dbg("PLAN", "计划为空，中止")
        return {"plan": plan, "reply": "", "error": "empty plan"}

    print("\n--- 计划清单 ---")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")
    print(f"理由: {plan.get('rationale') or '(无)'}")
    print("----------------\n")

    # 2) Execute
    print(">>> PHASE 2: EXECUTE\n")
    state = _initial_state(message)
    state["plan"] = plan
    for idx, step in enumerate(steps, 1):
        print(f"\n----- step {idx}/{len(steps)} -----")
        await execute_step(state, step, dry_exec=dry_exec or dry_run)
        if step.get("id") in ("report", "finish") and state.get("reply"):
            _dbg("EXEC", "已得到报告，提前结束后续步骤")
            break
        if step.get("id") == "finish":
            break

    print("\n>>> PHASE 3: DONE\n")
    _dbg(
        "DONE",
        "执行完成",
        skill_key=state.get("skill_key"),
        exec_log=state.get("exec_log"),
        has_reply=bool(state.get("reply")),
    )
    print("\n" + "=" * 60)
    print("最终报告 / reply")
    print("=" * 60)
    print(state.get("reply") or "(无 reply)")
    print("=" * 60)
    return state


def _default_message() -> str:
    return (
        "P1 【指标】：页面白屏\n【配置ID】：11664\n"
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?marketConfigId=11664&bizType=30"
    )


async def _amain(args: argparse.Namespace) -> None:
    from app.agents.alarm.browser import close_browser

    msg = args.message or _default_message()
    try:
        await run_pe_demo(
            msg,
            dry_run=args.dry_run,
            dry_exec=args.dry_exec,
        )
    finally:
        if not (args.dry_run or args.dry_exec):
            try:
                await close_browser()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="告警 Plan&Execute 测试 Demo")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="固定计划 + 模拟执行（不调 LLM、不拉数）",
    )
    parser.add_argument(
        "--dry-exec",
        action="store_true",
        help="仍用 LLM 规划，但执行用模拟数据",
    )
    parser.add_argument(
        "--message",
        type=str,
        default="",
        help="自定义告警正文；默认用内置 demo 文案",
    )
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
