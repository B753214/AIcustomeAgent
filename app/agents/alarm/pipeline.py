"""告警约束型 Pipeline：状态 + 步骤目录 + Replan + 执行。"""
from __future__ import annotations

import inspect
import asyncio
import time
from pydantic import ValidationError
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.agents.alarm.classify import SKILL_MAP, classify_alarm
from app.agents.alarm.fetcher import fetch_monitor_data, merge_monitor_details
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message
from app.agents.alarm.replan import EvidenceOutputError, assess_evidence, should_switch_playbook
from app.agents.alarm.report import (
    analyze_error_details,
    build_skip_report,
    should_skip_analysis,
)
from app.config import settings
from app.services.resilience import ainvoke_with_retry

STEP_PARSE = "parse"
STEP_CLASSIFY = "classify"
STEP_FETCH = "fetch"
STEP_ANALYZE = "analyze_detail"
STEP_SKIP_REPORT = "skip_report"
STEP_REPORT = "report"
STEP_FETCH_PAGE2 = "fetch_page2"
STEP_SWITCH_PLAYBOOK = "switch_playbook"
STEP_FINISH = "finish"

StageCb = Callable[[str, dict], Awaitable[None] | None]
ProgressCb = Callable[[str], Awaitable[None] | None]


def initial_state(message: str) -> dict:
    page_size = int(getattr(settings, "alarm_detail_page_size", 20) or 20)
    return {
        "message": message,
        "parsed": {},
        "skill_key": None,
        "skill_key_initial": None,
        "skill_meta": {},
        "page": 1,
        "page_size": page_size,
        "fetched_pages": [],
        "playbook_switched": False,
        "config_id": "",
        "biz_type": "30",
        "start_time": None,
        "end_time": None,
        "fetch_res": None,
        "monitor_rate": {},
        "monitor_detail": None,
        "pagination": None,
        "error_analysis": None,
        "skip_reason": None,
        "reply": None,
        "sources": [],
        "fetch_meta": {},
        "replans": [],
        "plan": [],
        "idempotency_keys": [],
        "evidence_decisions": [], "evidence_stop_reason": None,
        "last_fetch_ok": False, "last_page_count": 0, "has_more": None,
    }


def build_initial_plan(_state: dict) -> list[dict]:
    return [
        {"id": STEP_PARSE},
        {"id": STEP_CLASSIFY},
        {"id": STEP_FETCH, "page": 1},
        {"id": STEP_ANALYZE},
    ]


async def _emit(cb: StageCb | ProgressCb | None, *args) -> None:
    if not cb:
        return
    result = cb(*args)
    if inspect.isawaitable(result):
        await result


def _resolve_url_params(
    parsed: dict, message: str
) -> tuple[str, str, str | None, str | None]:
    detail_url = parsed.get("detailUrl") or extract_monitor_url(message) or ""
    if detail_url:
        parsed["detailUrl"] = detail_url
    qs = parse_qs(urlparse(detail_url).query) if detail_url else {}
    config_id = (
        parsed.get("configId") or (qs.get("marketConfigId") or [""])[0] or ""
    ).strip()
    if config_id:
        parsed["configId"] = config_id
    biz_type = (qs.get("bizType") or ["30"])[0]
    start_time = (qs.get("startTime") or [None])[0]
    end_time = (qs.get("endTime") or [None])[0]
    return config_id, biz_type, start_time, end_time


def _enrich_rate(rate: dict, parsed: dict) -> dict:
    out = dict(rate or {})
    if not out.get("name"):
        out["name"] = parsed.get("indicator") or out.get("remark") or "未知"
    if out.get("count") is None and parsed.get("current") is not None:
        out["count"] = parsed.get("current")
    if out.get("yesterdayCount") is None:
        out["yesterdayCount"] = parsed.get("yesterdayValue")
    if out.get("lastWeekCount") is None:
        out["lastWeekCount"] = parsed.get("lastWeekValue")
    return out


async def _step_parse(state: dict) -> None:
    message = state.get("message") or ""
    parsed = parse_alarm_message(message)
    config_id, biz_type, start_time, end_time = _resolve_url_params(parsed, message)
    state["parsed"] = parsed
    state["config_id"] = config_id
    state["biz_type"] = biz_type or "30"
    state["start_time"] = start_time
    state["end_time"] = end_time


async def _step_classify(state: dict) -> None:
    cls = classify_alarm(state.get("parsed") or {})
    state["skill_meta"] = cls
    state["skill_key"] = cls.get("key")


async def _step_fetch(state: dict, step: dict, *, on_progress: ProgressCb | None = None) -> None:
    page = int(step.get("page") or state.get("page") or 1)
    page_size = int(state.get("page_size") or 50)
    config_id = (state.get("config_id") or "").strip()
    if not config_id:
        state["fetch_res"] = None
        state["pagination"] = None
        state["fetch_meta"] = {
            "fetch_channel": "text_fallback",
            "config_id": "",
            "page": page,
            "pageSize": page_size,
        }
        return
    keys = state.setdefault("idempotency_keys", [])
    fetched_pages = state.setdefault("fetched_pages", [])
    key = f"fetch:{config_id}:p{page}"
    if key in keys:
        state["page"] = page
        if page not in fetched_pages:
            fetched_pages.append(page)
        await _emit(on_progress, f"跳过重复拉取 {key}")
        return

    res = await fetch_monitor_data(
        market_config_id=config_id,
        biz_type=state.get("biz_type") or "30",
        start_time=state.get("start_time"),
        end_time=state.get("end_time"),
        raw_url=(state.get("parsed") or {}).get("detailUrl") or "",
        on_progress=on_progress,
        page=page,
        page_size=page_size,
    )
    if page > 1 and res and res.get("monitorDetail") is None:
        res = None
    state["last_fetch_ok"] = bool(res)
    if not res:
        state.setdefault("fetch_errors", []).append({"page": page, "reason": "fetch_failed"})
        if not state.get("fetch_res"):
            state["pagination"] = None
            state["fetch_meta"] = {"fetch_channel": "text_fallback", "config_id": config_id}
        return

    keys.append(key)
    state["fetch_res"] = res
    state["page"] = page
    if page not in fetched_pages:
        fetched_pages.append(page)

    parsed = state.get("parsed") or {}
    if page == 1 or not state.get("monitor_rate"):
        state["monitor_rate"] = _enrich_rate(dict(res.get("monitorRate") or {}), parsed)

    detail = res.get("monitorDetail")
    rows = detail if isinstance(detail, list) else (detail or {}).get("list", [])
    state["last_page_count"] = len(rows)
    state["has_more"] = res.get("has_more", len(rows) >= page_size)
    if state.get("monitor_detail") is None:
        state["monitor_detail"] = detail
    else:
        state["monitor_detail"] = merge_monitor_details(state["monitor_detail"], detail)

    state["pagination"] = res.get("pagination")
    state["fetch_meta"] = {
        "fetch_channel": res.get("channel") or "text_fallback",
        "config_id": config_id,
        "page": page,
        "pageSize": res.get("pageSize") or page_size,
    }


async def _step_analyze(state: dict) -> None:
    detail = state.get("monitor_detail")
    if detail is not None:
        state["error_analysis"] = analyze_error_details(detail)
    else:
        state["error_analysis"] = None

    rate = state.get("monitor_rate") or {}
    if state.get("fetch_res") and settings.alarm_skip_when_zero_count:
        state["skip_reason"] = should_skip_analysis(rate)
    else:
        state["skip_reason"] = None


async def _step_switch_playbook(state: dict, new_key: str) -> None:
    meta = SKILL_MAP.get(new_key) or SKILL_MAP["precise"]
    state["skill_meta"] = {"key": new_key, **meta}
    state["skill_key"] = new_key
    state["playbook_switched"] = True


async def _step_skip_report(state: dict) -> None:
    parsed = state.get("parsed") or {}
    meta = state.get("fetch_meta") or {}
    state["reply"] = build_skip_report(
        state.get("skip_reason") or "当前无失败",
        monitor_url=parsed.get("detailUrl") or "",
        channel=meta.get("fetch_channel") or "",
    )
    sources: list[str] = []
    if parsed.get("detailUrl"):
        sources.append(parsed["detailUrl"])
    if state.get("skill_key"):
        sources.append(f"skill:{state['skill_key']}")
    sources.append(f"channel:{meta.get('fetch_channel') or 'text_fallback'}")
    state["sources"] = sources


async def _step_report(state: dict) -> None:
    from app.agents.alarm import runner as alarm_runner

    message = state.get("message") or ""
    parsed = state.get("parsed") or {}
    cls = state.get("skill_meta") or {"key": state.get("skill_key") or "precise"}
    config_id = state.get("config_id") or ""
    res = {
        "channel": (state.get("fetch_meta") or {}).get("fetch_channel") or "text_fallback",
        "monitorRate": state.get("monitor_rate") or {},
        "monitorDetail": state.get("monitor_detail"),
    }
    if not state.get("fetch_res"):
        res = None
    messages, sources, fetch_meta, error_analysis = alarm_runner._assemble(
        message, parsed, cls, config_id, res,
        evidence_context={"decisions": state.get("evidence_decisions") or [],
                          "stop_reason": state.get("evidence_stop_reason")},
    )
    state["sources"] = sources
    state["fetch_meta"] = {**(state.get("fetch_meta") or {}), **fetch_meta}
    if error_analysis is not None:
        state["error_analysis"] = error_analysis
    llm = alarm_runner._build_llm()
    response = await ainvoke_with_retry(llm.ainvoke, messages)
    ai_text = response.content if hasattr(response, "content") else str(response)
    state["reply"] = alarm_runner._finalize_reply(
        ai_text,
        rate=state.get("monitor_rate") or {},
        error_analysis=state.get("error_analysis"),
        monitor_url=parsed.get("detailUrl") or "",
        channel=(state.get("fetch_meta") or {}).get("fetch_channel") or "",
        cls=cls,
    )


async def run_step(
    state: dict,
    step: dict,
    *,
    on_progress: ProgressCb | None = None,
) -> dict:
    step_id = step.get("id")
    if step_id == STEP_PARSE:
        await _step_parse(state)
    elif step_id == STEP_CLASSIFY:
        await _step_classify(state)
    elif step_id in (STEP_FETCH, STEP_FETCH_PAGE2):
        await _step_fetch(state, step, on_progress=on_progress)
    elif step_id == STEP_ANALYZE:
        await _step_analyze(state)
    elif step_id == STEP_SKIP_REPORT:
        await _step_skip_report(state)
    elif step_id == STEP_REPORT:
        await _step_report(state)
    else:
        raise NotImplementedError(f"step not implemented: {step_id}")
    return state


async def _run_replan_loop(
    state: dict,
    *,
    on_progress: ProgressCb | None = None,
    on_stage: StageCb | None = None,
) -> None:
    """先由 LLM 判断证据，再在页数/时间边界内补页。"""
    max_pages = max(1, int(settings.alarm_replan_max_pages))
    deadline = time.monotonic() + settings.alarm_replan_time_budget_sec
    decisions = state.setdefault("evidence_decisions", [])
    # 手册更换仍是独立规则；它不再参与补页仲裁。
    if settings.alarm_replan_max_playbook_switch > 0:
        hint = should_switch_playbook(
            skill_key=state.get("skill_key") or "",
            playbook_switched=bool(state.get("playbook_switched")),
            alarm_type=(state.get("parsed") or {}).get("alarmType"),
            error_analysis=state.get("error_analysis"),
            monitor_detail=state.get("monitor_detail"),
        )
        if hint:
            await _step_switch_playbook(state, hint)
            state.setdefault("replans", []).append(f"switch_playbook:{hint}")
            await _emit(on_stage, f"更换 playbook 为 {hint}", {"replan": "switch_playbook"})

    for _ in range(max_pages):
        if state.get("skip_reason"):
            return
        if not state.get("monitor_detail") or not state.get("error_analysis"):
            state["evidence_stop_reason"] = "no_detail"
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            state["evidence_stop_reason"] = "time_budget"
            return
        try:
            decision = await asyncio.wait_for(assess_evidence(state), timeout=remaining)
        except (ValidationError, EvidenceOutputError) as exc:
            state["evidence_stop_reason"] = "assessment_invalid"
            # 不记录原始模型输出或异常正文，只保留字段位置和错误类型。
            state["evidence_validation_errors"] = [
                {"field": ".".join(str(p) for p in err["loc"]) or "response",
                 "type": err["type"]}
                for err in exc.errors(include_input=False, include_context=False)[:10]
            ] if isinstance(exc, ValidationError) else [{"field": "response", "type": "structured_output_error"}]
            await _emit(on_stage, "证据评估输出校验失败，停止补页并基于已有数据生成报告",
                        {"replan": "finish", "stop_reason": "assessment_invalid"})
            return
        except Exception:
            state["evidence_stop_reason"] = "assessment_failed"
            await _emit(on_stage, "证据评估失败，基于已有数据生成报告", {"replan": "finish"})
            return
        decisions.append(decision.model_dump())
        await _emit(on_stage, f"证据评估：{decision.reason}", decision.model_dump())
        if decision.action != "fetch_next_page":
            state["evidence_stop_reason"] = decision.action
            return
        fetched = state.get("fetched_pages") or []
        if len(fetched) >= max_pages:
            state["evidence_stop_reason"] = "page_limit"
            return
        if (state.get("pagination") not in ("browser", "browser_only")
                or not settings.alarm_browser_enabled
                or not (state.get("parsed") or {}).get("detailUrl")):
            state["evidence_stop_reason"] = "pagination_unavailable"
            return
        if state.get("has_more") is False:
            state["evidence_stop_reason"] = "no_more_pages"
            return
        next_page = max(fetched or [1]) + 1
        detail = state.get("monitor_detail")
        old_rows = detail if isinstance(detail, list) else detail.get("list", [])
        old_count = len(old_rows)
        await _emit(on_stage, f"证据不足，补拉第 {next_page} 页明细…",
                    {"replan": "fetch_next_page", "page": next_page})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            state["evidence_stop_reason"] = "time_budget"
            return
        try:
            await asyncio.wait_for(
                _step_fetch(state, {"id": STEP_FETCH, "page": next_page}, on_progress=on_progress),
                timeout=remaining,
            )
        except Exception:
            state["evidence_stop_reason"] = "fetch_failed"
            return
        if not state.get("last_fetch_ok"):
            state["evidence_stop_reason"] = "fetch_failed"
            return
        state.setdefault("replans", []).append(f"fetch_page:{next_page}")
        await _step_analyze(state)
        detail = state.get("monitor_detail")
        rows = detail if isinstance(detail, list) else (detail or {}).get("list", [])
        if len(rows) <= old_count:
            state["evidence_stop_reason"] = "no_new_evidence"
            return
    state["evidence_stop_reason"] = "page_limit"


async def run_initial_pipeline(
    message: str,
    *,
    on_progress: ProgressCb | None = None,
    on_stage: StageCb | None = None,
    stop_before_report: bool = False,
) -> dict:
    state = initial_state(message)
    state["plan"] = build_initial_plan(state)
    while state["plan"]:
        step = state["plan"].pop(0)
        await run_step(state, step, on_progress=on_progress)

    state["skill_key_initial"] = state.get("skill_key")

    if state.get("skip_reason"):
        if not stop_before_report:
            await run_step(state, {"id": STEP_SKIP_REPORT})
        return state

    if settings.alarm_replan_enabled:
        await _run_replan_loop(state, on_progress=on_progress, on_stage=on_stage)

    if not stop_before_report:
        await run_step(state, {"id": STEP_REPORT})

    return state


async def main() -> None:
    from app.agents.alarm.browser import close_browser

    msg = (
        "P1 【指标】：页面白屏\n【配置ID】：11664\n"
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?marketConfigId=11664&bizType=30"
    )
    try:
        state = await run_initial_pipeline(msg)
        print(state.get("fetch_meta"))
        print("replans:", state.get("replans"))
        print("skip_reason:", state.get("skip_reason"))
        print("reply:", (state.get("reply") or "")[:200])
    finally:
        await close_browser()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
