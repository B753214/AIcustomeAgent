"""告警 Agent：parse → classify → playbook → 拉数 →（可选 skip）→ LLM → 报告。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.fetcher import fetch_monitor_data
from app.agents.alarm.format import format_detail_for_llm
from app.agents.alarm.load_playbooks import load_playbook
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message
from app.agents.alarm.report import (
    analyze_error_details,
    build_skip_report,
    build_url_report,
    should_skip_analysis,
)
from app.config import settings
from app.services.resilience import ainvoke_with_retry

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


def _resolve_url_params(parsed: dict, message: str) -> tuple[str, str, str | None, str | None]:
    detail_url = parsed.get("detailUrl") or extract_monitor_url(message) or ""
    if detail_url:
        parsed["detailUrl"] = detail_url
    qs = parse_qs(urlparse(detail_url).query) if detail_url else {}
    config_id = (parsed.get("configId") or (qs.get("marketConfigId") or [""])[0] or "").strip()
    if config_id:
        parsed["configId"] = config_id
    biz_type = (qs.get("bizType") or ["30"])[0]
    start_time = (qs.get("startTime") or [None])[0]
    end_time = (qs.get("endTime") or [None])[0]
    return config_id, biz_type, start_time, end_time


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
) -> dict:
    meta = {
        "skill_key": cls.get("key"),
        "config_id": parsed.get("configId"),
        "detail_url": parsed.get("detailUrl") or "",
        "skill_type": cls.get("type"),
        "fetch_channel": (fetch_meta or {}).get("fetch_channel", "text_fallback"),
        "skip": skip,
        "report_format": settings.alarm_report_format,
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


async def _prepare(
    message: str,
    on_progress: Any = None,
) -> tuple[list | None, dict, dict, list[str], dict, dict | None, dict, str | None]:
    """
    返回:
      messages(可 None=skip), parsed, cls, sources, fetch_meta,
      error_analysis, rate, skip_reason
    """
    parsed = parse_alarm_message(message)
    config_id, biz_type, start_time, end_time = _resolve_url_params(parsed, message)
    cls = classify_alarm(parsed)

    res = None
    if config_id:
        res = await fetch_monitor_data(
            market_config_id=config_id,
            biz_type=biz_type,
            start_time=start_time,
            end_time=end_time,
            raw_url=parsed.get("detailUrl") or "",
            on_progress=on_progress,
        )

    rate = _rate_from_res(res, parsed)
    fetch_channel = (res or {}).get("channel") or "text_fallback"
    skip_reason = None
    if settings.alarm_skip_when_zero_count:
        skip_reason = should_skip_analysis(rate if res else None)

    if skip_reason:
        sources: list[str] = []
        if parsed.get("detailUrl"):
            sources.append(parsed["detailUrl"])
        if cls.get("key"):
            sources.append(f"skill:{cls['key']}")
        sources.append(f"channel:{fetch_channel}")
        fetch_meta = {"fetch_channel": fetch_channel, "config_id": config_id}
        return None, parsed, cls, sources, fetch_meta, None, rate, skip_reason

    messages, sources, fetch_meta, error_analysis = _assemble(
        message, parsed, cls, config_id, res
    )
    return messages, parsed, cls, sources, fetch_meta, error_analysis, rate, None


async def run_alarm_agent(message: str) -> dict:
    """非流式：供 JSON /chat、Crew Tool 使用。"""
    messages, parsed, cls, sources, fetch_meta, error_analysis, rate, skip_reason = (
        await _prepare(message)
    )
    if skip_reason:
        reply = build_skip_report(
            skip_reason,
            monitor_url=parsed.get("detailUrl") or "",
            channel=fetch_meta.get("fetch_channel", ""),
        )
        return _result_dict(reply, parsed, cls, sources, fetch_meta, skip=True)

    llm = _build_llm()
    response = await ainvoke_with_retry(llm.ainvoke, messages)
    ai_text = response.content if hasattr(response, "content") else str(response)
    reply = _finalize_reply(
        ai_text,
        rate=rate,
        error_analysis=error_analysis,
        monitor_url=parsed.get("detailUrl") or "",
        channel=fetch_meta.get("fetch_channel", ""),
        cls=cls,
    )
    return _result_dict(reply, parsed, cls, sources, fetch_meta)


async def run_alarm_agent_stream(message: str) -> AsyncIterator[dict]:
    """流式：stage →（skip 或 token）→ done。"""
    progress_events: list[dict] = []

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
    messages, parsed, cls, sources, fetch_meta, error_analysis, rate, skip_reason = (
        await _prepare(message, on_progress=on_progress)
    )
    for ev in progress_events:
        yield ev

    if skip_reason:
        reply = build_skip_report(
            skip_reason,
            monitor_url=parsed.get("detailUrl") or "",
            channel=fetch_meta.get("fetch_channel", ""),
        )
        yield {
            "type": "stage",
            "stage": "alarm",
            "msg": f"跳过深入分析：{skip_reason}",
            "ok": True,
            "meta": {"skip": True, "fetch_channel": fetch_meta.get("fetch_channel")},
        }
        yield {"type": "token", "content": reply, "sources": sources}
        yield {
            "type": "done",
            **_result_dict(reply, parsed, cls, sources, fetch_meta, skip=True),
        }
        return

    yield {
        "type": "stage",
        "stage": "alarm",
        "msg": f"告警排查中（{cls.get('type') or cls.get('key') or 'generic'}，{fetch_meta.get('fetch_channel')}）",
        "ok": True,
        "meta": {
            "skill_key": cls.get("key"),
            "config_id": parsed.get("configId"),
            "fetch_channel": fetch_meta.get("fetch_channel"),
        },
    }
    llm = _build_llm()
    full_ai = ""
    async for chunk in llm.astream(messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        full_ai += token
        # rca 模式直接流式；markdown 模式先攒全文再出完整报告，避免半截章节
        if (settings.alarm_report_format or "").lower() == "rca":
            yield {"type": "token", "content": token, "sources": sources}

    reply = _finalize_reply(
        full_ai,
        rate=rate,
        error_analysis=error_analysis,
        monitor_url=parsed.get("detailUrl") or "",
        channel=fetch_meta.get("fetch_channel", ""),
        cls=cls,
    )
    if (settings.alarm_report_format or "").lower() != "rca":
        yield {"type": "token", "content": reply, "sources": sources}
    yield {"type": "done", **_result_dict(reply, parsed, cls, sources, fetch_meta)}
