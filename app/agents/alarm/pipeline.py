"""告警约束型 Pipeline：状态 + 步骤目录 + 执行（Day3，先不接 replan / runner）。"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.fetcher import fetch_monitor_data, merge_monitor_details
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message
from app.agents.alarm.report import analyze_error_details, should_skip_analysis
from app.config import settings
STEP_PARSE = "parse"
STEP_CLASSIFY = "classify"
STEP_FETCH = "fetch"
STEP_ANALYZE = "analyze_detail"
STEP_SKIP_REPORT = "skip_report"
STEP_REPORT = "report"
STEP_FETCH_PAGE2 = "fetch_page2"  # Day3 可先声明，execute 里暂不实现
STEP_SWITCH_PLAYBOOK = "switch_playbook"
STEP_FINISH = "finish"


def initial_state(message: str) -> dict:
    return {
        "message": message,
        "parsed": {},
        "skill_key": None,
        "skill_meta": {},  # classify 完整 {key,type,skill}
        "page": 1,
        "page_size": 50,
        "fetched_pages": [],
        "playbook_switched": False,
        "config_id": "",
        "biz_type": "30",
        "start_time": None,
        "end_time": None,
        "fetch_res": None,  # 最近一次 fetch 原始返回
        "monitor_rate": {},
        "monitor_detail": None,  # 合并后
        "pagination": None,
        "error_analysis": None,
        "skip_reason": None,
        "reply": None,
        "sources": [],
        "fetch_meta": {},
        "replans": [],
        "plan": [],  # 待执行步骤队列，如 [{"id":"fetch","page":1}, ...]
    }


def build_initial_plan(_state: dict) -> list[dict]:
    """首轮固定队列；skip/report 等 analyze 后再追加。"""
    return [
        {"id": STEP_PARSE},
        {"id": STEP_CLASSIFY},
        {"id": STEP_FETCH, "page": 1},
        {"id": STEP_ANALYZE},
    ]


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
    """对齐 runner._rate_from_res 的字段兜底。"""
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


async def _step_fetch(state: dict, step: dict) -> None:
    page = int(step.get("page") or state.get("page") or 1)
    page_size = int(state.get("page_size") or 50)
    config_id = (state.get("config_id") or "").strip()
    if not config_id:
        # 无 id：等价 runner 不拉数，走正文
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

    # 与 runner 一致：有拉数结果才考虑 count==0 skip
    rate = state.get("monitor_rate") or {}
    if state.get("fetch_res") and settings.alarm_skip_when_zero_count:
        state["skip_reason"] = should_skip_analysis(rate)
    else:
        state["skip_reason"] = None

def _append_report_step(state: dict) -> None:
    if state.get("skip_reason"):
        state["plan"].append({"id": STEP_SKIP_REPORT})
    else:
        state["plan"].append({"id": STEP_REPORT})

async def _step_skip_report(state: dict) -> None:
    parsed = state.get("parsed") or {}
    meta = state.get("fetch_meta") or {}
    state["reply"] = build_skip_report(
        state.get("skip_reason") or "当前无失败",
        monitor_url=parsed.get("detailUrl") or "",
        channel=meta.get("fetch_channel") or "",
    )
    # 可选：补 sources
    sources: list[str] = []
    if parsed.get("detailUrl"):
        sources.append(parsed["detailUrl"])
    if state.get("skill_key"):
        sources.append(f"skill:{state['skill_key']}")
    sources.append(f"channel:{meta.get('fetch_channel') or 'text_fallback'}")
    state["sources"] = sources

async def _step_report(state: dict) -> None:
    # Day4 再接 LLM；这里先占位，保证流水线能跑通
    state["reply"] = state.get("reply") or "[TODO] report step — LLM 未接入"
    parsed = state.get("parsed") or {}
    meta = state.get("fetch_meta") or {}
    sources: list[str] = []
    if parsed.get("detailUrl"):
        sources.append(parsed["detailUrl"])
    if state.get("skill_key"):
        sources.append(f"skill:{state['skill_key']}")
    sources.append(f"channel:{meta.get('fetch_channel') or 'text_fallback'}")
    state["sources"] = sources

async def run_step(state: dict, step: dict) -> dict:
    """执行单步，原地更新 state，并返回 state（方便链式调用）。"""
    step_id = step.get("id")
    if step_id == STEP_PARSE:
        await _step_parse(state)
    elif step_id == STEP_CLASSIFY:
        await _step_classify(state)
    elif step_id == STEP_FETCH:
        await _step_fetch(state, step)
    elif step_id == STEP_ANALYZE:
        await _step_analyze(state)
    elif step_id == STEP_SKIP_REPORT:
        await _step_skip_report(state)
    elif step_id == STEP_REPORT:
        await _step_report(state)
    else:
        raise NotImplementedError(f"step not implemented: {step_id}")
    return state

async def run_initial_pipeline(message: str) -> dict:
    """无 Replan 的首轮执行；等价 runner 的 prepare 阶段 + 报告占位。"""
    state = initial_state(message)
    state["plan"] = build_initial_plan(state)
    while state["plan"]:
        step = state["plan"].pop(0)
        await run_step(state, step)
        if step.get("id") == STEP_ANALYZE:
            _append_report_step(state)
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
        print("skip_reason:", state.get("skip_reason"))
        print("reply:", (state.get("reply") or "")[:200])
    finally:
        await close_browser()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
