"""告警约束型 Pipeline：状态 + 步骤目录 + Replan + 执行。"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.agents.alarm.classify import SKILL_MAP, classify_alarm
from app.agents.alarm.fetcher import fetch_monitor_data, merge_monitor_details
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message
from app.agents.alarm.replan import should_fetch_page2, should_switch_playbook, llm_pick_replan_action
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
    state["fetch_res"] = res
    state["page"] = page
    if page not in state["fetched_pages"]:
        state["fetched_pages"].append(page)

    if not res:
        state["pagination"] = None
        state["fetch_meta"] = {
            "fetch_channel": "text_fallback",
            "config_id": config_id,
            "page": page,
            "pageSize": page_size,
        }
        return

    parsed = state.get("parsed") or {}
    state["monitor_rate"] = _enrich_rate(dict(res.get("monitorRate") or {}), parsed)

    detail = res.get("monitorDetail")
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
        message, parsed, cls, config_id, res
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
    """Replan：补页与换本冲突时 LLM 三选一；否则先补页再换本；每轮最多改一项，总循环 ≤ 3。"""
    max_pages = int(getattr(settings, "alarm_replan_max_pages", 2))
    max_switch = int(getattr(settings, "alarm_replan_max_playbook_switch", 1))
    page_size = int(state.get("page_size") or 50)
    parsed = state.get("parsed") or {}

    for _ in range(3):
        changed = False
        fetched = state.get("fetched_pages") or []

        want_page2 = (
            len(fetched) < max_pages
            and should_fetch_page2(
                page=int(state.get("page") or 1),
                page_size=page_size,
                fetched_pages=fetched,
                monitor_rate=state.get("monitor_rate"),
                error_analysis=state.get("error_analysis"),
                pagination=state.get("pagination"),
                draft_report=None,
            )
        )

        hint_key = None
        if max_switch > 0 and not state.get("playbook_switched") and not state.get("skip_reason"):
            hint_key = should_switch_playbook(
                skill_key=str(state.get("skill_key") or ""),
                playbook_switched=bool(state.get("playbook_switched")),
                alarm_type=parsed.get("alarmType"),
                error_analysis=state.get("error_analysis"),
                monitor_detail=state.get("monitor_detail"),
            )

        choice = None
        if want_page2 and hint_key:
            choice = await llm_pick_replan_action(
                skill_key=str(state.get("skill_key") or ""),
                hint_key=hint_key,
                error_analysis=state.get("error_analysis"),
                monitor_rate=state.get("monitor_rate"),
            )
            if choice == "finish":
                break

        if want_page2 and hint_key:
            if choice == "fetch_page2" or choice is None:
                action = "fetch_page2"
            elif choice.startswith("switch_playbook:"):
                action = "switch_playbook"
            else:
                action = None
        elif want_page2:
            action = "fetch_page2"
        elif hint_key:
            action = "switch_playbook"
        else:
            action = None

        if action == "fetch_page2":
            await _emit(
                on_stage,
                "证据偏弱，补拉第 2 页明细…",
                {"replan": "fetch_page2", "page": 2},
            )
            await _step_fetch(state, {"id": STEP_FETCH, "page": 2}, on_progress=on_progress)
            await _step_analyze(state)
            state.setdefault("replans", []).append("fetch_page2")
            changed = True
            continue

        if action == "switch_playbook" and hint_key:
            old_key = state.get("skill_key")
            await _emit(
                on_stage,
                f"明细指向 {hint_key}，更换 playbook（原 {old_key}）…",
                {"replan": f"switch_playbook:{hint_key}", "from": old_key, "to": hint_key},
            )
            await _step_switch_playbook(state, hint_key)
            state.setdefault("replans", []).append(f"switch_playbook:{hint_key}")
            changed = True
            continue

        if not changed:
            break


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
