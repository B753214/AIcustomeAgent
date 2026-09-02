"""告警 Agent：pipeline 拉数 + Replan + LLM 报告（非流式 / SSE）。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.alarm.format import format_detail_for_llm
from app.agents.alarm.load_playbooks import load_playbook
from app.agents.alarm.pipeline import run_initial_pipeline, run_step, STEP_SKIP_REPORT
from app.agents.alarm.report import analyze_error_details, build_url_report
from app.config import settings

_OUTPUT_FORMAT = """
你必须严格按以下格式输出，不要加任何 markdown 符号（不要用 ##、** 等），不要输出额外内容：

排查结论
{一段话描述问题现象和根因分析}
证据链
1. {证据1}
2. {证据2}
（可以有更多条）
修复建议
短期：{短期修复建议}
长期：{长期改进建议}
""".strip()


def _build_llm():
    return init_chat_model(
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        model=settings.AIROBOT_LLM_MODEL,
        model_provider=settings.provider,
    )


def _channel_label(channel: str) -> str:
    return {
        "mcp": "经 MCP 拉取",
        "browser": "经浏览器拉取",
        "text_fallback": "未拉到实时数据",
    }.get(channel, channel)


def _rate_from_res(res: dict | None, parsed: dict) -> dict:
    rate = dict((res or {}).get("monitorRate") or {})
    if not rate.get("name"):
        rate["name"] = parsed.get("indicator") or rate.get("remark") or "未知"
    if rate.get("count") is None and parsed.get("current") is not None:
        rate["count"] = parsed.get("current")
    if rate.get("yesterdayCount") is None:
        rate["yesterdayCount"] = parsed.get("yesterdayValue")
    if rate.get("lastWeekCount") is None:
        rate["lastWeekCount"] = parsed.get("lastWeekValue")
    return rate


def _assemble(
    message: str,
    parsed: dict,
    cls: dict,
    config_id: str,
    res: dict | None,
) -> tuple[list, list[str], dict, dict | None]:
    """返回 messages, sources, fetch_meta, error_analysis。"""
    playbook = load_playbook(cls["key"])
    system_prompt = (playbook or "") + "\n\n" + _OUTPUT_FORMAT

    fetch_meta: dict[str, Any] = {
        "fetch_channel": (res or {}).get("channel") or "text_fallback",
        "config_id": config_id,
    }
    rate = _rate_from_res(res, parsed)
    name = rate.get("name") or "未知"
    count = rate.get("count")
    yesterday = rate.get("yesterdayCount")
    last_week = rate.get("lastWeekCount")

    error_analysis = None
    if res and res.get("monitorDetail") is not None:
        error_analysis = analyze_error_details(res.get("monitorDetail"))

    user_prompt = f"""请分析以下监控告警数据：

监控名称：{name}
配置ID：{parsed.get("configId") or config_id or "未知"}
当前失败次数：{count if count is not None else "未知"}
昨日失败次数：{yesterday if yesterday is not None else "未知"}
上周失败次数：{last_week if last_week is not None else "未知"}
命中规则：{parsed.get("hitRule") or "未知"}
监控链接：{parsed.get("detailUrl") or "无"}
原文：
{message[:1500]}
"""
    channel = fetch_meta["fetch_channel"]
    if res:
        detail_text = format_detail_for_llm(res.get("monitorDetail"))
        user_prompt += f"\n错误明细（{_channel_label(channel)}）：\n{detail_text}\n"
        if error_analysis:
            tops = "；".join(error_analysis.get("topErrors") or [])
            user_prompt += f"\n规则汇总：共{error_analysis.get('total')}条明细"
            if tops:
                user_prompt += f"；Top错误：{tops}"
            if error_analysis.get("isSingleUser"):
                user_prompt += f"；疑似单用户 uid={error_analysis.get('singleUid')}"
            user_prompt += "\n"
    else:
        user_prompt += "\n【说明】未拉到实时监控数据，仅依据告警正文分析。\n"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    detail_url = parsed.get("detailUrl") or ""
    sources: list[str] = [detail_url] if detail_url else []
    if cls.get("key"):
        sources.append(f"skill:{cls['key']}")
    sources.append(f"channel:{channel}")
    return messages, sources, fetch_meta, error_analysis


def _finalize_reply(
    ai_text: str,
    *,
    rate: dict,
    error_analysis: dict | None,
    monitor_url: str,
    channel: str,
    cls: dict,
) -> str:
    fmt = (settings.alarm_report_format or "markdown").strip().lower()
    if fmt == "rca":
        return ai_text
    return build_url_report(
        rate,
        error_analysis,
        monitor_url or None,
        ai_text,
        channel=channel,
        skill=cls,
    )


def _result_dict(
    reply: str,
    parsed: dict,
    cls: dict,
    sources: list[str],
    fetch_meta: dict | None = None,
    *,
    skip: bool = False,
    replans: list[str] | None = None,
    page_count: int | None = None,
    skill_key_initial: str | None = None,
) -> dict:
    meta = {
        "skill_key": cls.get("key"),
        "config_id": parsed.get("configId"),
        "detail_url": parsed.get("detailUrl") or "",
        "skill_type": cls.get("type"),
        "fetch_channel": (fetch_meta or {}).get("fetch_channel", "text_fallback"),
        "skip": skip,
        "report_format": settings.alarm_report_format,
        "replans": replans or [],
        "page_count": page_count,
        "skill_key_initial": skill_key_initial,
    }
    return {
        "reply": reply,
        "intent": "alarm",
        "sources": sources,
        "engine": "alarm",
        "cache_hit": False,
        "meta": meta,
        "skip": skip,
    }


def _result_from_state(state: dict, *, skip: bool | None = None) -> dict:
    return _result_dict(
        state.get("reply") or "",
        state["parsed"],
        state.get("skill_meta") or {},
        state.get("sources") or [],
        state.get("fetch_meta") or {},
        skip=skip if skip is not None else bool(state.get("skip_reason")),
        replans=state.get("replans") or [],
        page_count=len(state.get("fetched_pages") or []),
        skill_key_initial=state.get("skill_key_initial"),
    )


async def run_alarm_agent(message: str) -> dict:
    """非流式：供 JSON /chat、Crew Tool 使用。"""
    state = await run_initial_pipeline(message)
    return _result_from_state(state)


async def run_alarm_agent_stream(message: str) -> AsyncIterator[dict]:
    """流式：stage →（skip 或 token）→ done。"""
    progress_events: list[dict] = []
    replan_events: list[dict] = []

    async def on_stage(msg: str, meta: dict | None = None) -> None:
        replan_events.append(
            {
                "type": "stage",
                "stage": "alarm_replan",
                "msg": msg,
                "ok": True,
                "meta": meta or {},
            }
        )

    async def on_progress(msg: str) -> None:
        progress_events.append(
            {"type": "stage", "stage": "alarm_fetch", "msg": msg, "ok": True}
        )

    yield {
        "type": "stage",
        "stage": "alarm_fetch",
        "msg": "正在解析告警并尝试拉取监控数据…",
        "ok": True,
    }
    state = await run_initial_pipeline(
        message,
        on_progress=on_progress,
        on_stage=on_stage,
        stop_before_report=True,
    )
    for ev in progress_events:
        yield ev
    for ev in replan_events:
        yield ev

    parsed = state["parsed"]
    cls = state["skill_meta"]
    fetch_meta = state.get("fetch_meta") or {}

    if state.get("skip_reason"):
        await run_step(state, {"id": STEP_SKIP_REPORT})
        reply = state["reply"]
        yield {
            "type": "stage",
            "stage": "alarm",
            "msg": f"跳过深入分析：{state['skip_reason']}",
            "ok": True,
            "meta": {"skip": True, "fetch_channel": fetch_meta.get("fetch_channel")},
        }
        yield {"type": "token", "content": reply, "sources": state["sources"]}
        yield {"type": "done", **_result_from_state(state, skip=True)}
        return

    res = None if not state.get("fetch_res") else {
        "channel": fetch_meta.get("fetch_channel"),
        "monitorRate": state.get("monitor_rate"),
        "monitorDetail": state.get("monitor_detail"),
    }
    messages, sources, fetch_meta, _ = _assemble(
        message, parsed, cls, state["config_id"], res
    )

    yield {
        "type": "stage",
        "stage": "alarm",
        "msg": f"告警排查中（{cls.get('type') or cls.get('key') or 'generic'}，{fetch_meta.get('fetch_channel')}）",
        "ok": True,
        "meta": {
            "skill_key": cls.get("key"),
            "config_id": parsed.get("configId"),
            "fetch_channel": fetch_meta.get("fetch_channel"),
            "replans": state.get("replans") or [],
        },
    }
    llm = _build_llm()
    full_ai = ""
    async for chunk in llm.astream(messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        full_ai += token
        if (settings.alarm_report_format or "").lower() == "rca":
            yield {"type": "token", "content": token, "sources": sources}

    reply = _finalize_reply(
        full_ai,
        rate=state.get("monitor_rate") or {},
        error_analysis=state.get("error_analysis"),
        monitor_url=parsed.get("detailUrl") or "",
        channel=fetch_meta.get("fetch_channel", ""),
        cls=cls,
    )
    if (settings.alarm_report_format or "").lower() != "rca":
        yield {"type": "token", "content": reply, "sources": sources}
    state["reply"] = reply
    state["sources"] = sources
    state["fetch_meta"] = fetch_meta
    yield {"type": "done", **_result_from_state(state)}


async def _demo_stream(message: str) -> None:
    from app.agents.alarm.browser import close_browser

    fmt_rca = (settings.alarm_report_format or "").lower() == "rca"
    got_token = False
    try:
        async for ev in run_alarm_agent_stream(message):
            kind = ev.get("type")
            if kind == "token":
                got_token = True
                print(ev.get("content", ""), end="" if fmt_rca else "\n")
            elif kind == "done":
                print("\n" + "=" * 60)
                print("DONE")
                # markdown：正文已在 token 输出；rca：token 已流式打印，done 仅 meta
                if not got_token:
                    print(ev.get("reply") or "")
                print("meta.replans:", (ev.get("meta") or {}).get("replans"))
                print("=" * 60)
            else:
                print(f"[{kind}] {ev.get('msg') or ev.get('stage') or ev.get('meta')}")
    finally:
        await close_browser()


if __name__ == "__main__":
    import asyncio

    demo = (
        "P1 【指标】：页面白屏\n【配置ID】：11664\n"
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?marketConfigId=11664&bizType=30"
    )
    asyncio.run(_demo_stream(demo))