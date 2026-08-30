"""告警 Agent：parse → classify → playbook →（可选 MCP）→ LLM 报告。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.fetcher import fetch_monitor_data
from app.agents.alarm.load_playbooks import load_playbook
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message
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

_DETAIL_MAX_CHARS = 3000


def _build_llm():
    return init_chat_model(
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        model=settings.AIROBOT_LLM_MODEL,
        model_provider=settings.provider,
    )


def _format_detail_for_llm(detail_data: Any) -> str:
    """对齐 fc_monitor.js formatDetailForLLM。"""
    if detail_data is None:
        return "无明细数据"
    if isinstance(detail_data, list):
        items = detail_data
    elif isinstance(detail_data, dict):
        items = detail_data.get("list") or []
        if not isinstance(items, list):
            items = []
    else:
        return "无明细数据"
    if not items:
        return "无明细数据"

    rows: list[str] = []
    for i, item in enumerate(items[:50]):
        if not isinstance(item, dict):
            continue
        parts: list[str] = []
        if item.get("time"):
            parts.append(f"时间:{item['time']}")
        if item.get("err_msg"):
            parts.append(f"错误:{item['err_msg']}")
        if item.get("err_flag"):
            parts.append(f"标志:{item['err_flag']}")
        if item.get("url"):
            parts.append(f"接口:{item['url']}")
        if item.get("page_name"):
            parts.append(f"页面:{item['page_name']}")
        if item.get("scene"):
            parts.append(f"场景:{item['scene']}")
        if item.get("uid"):
            parts.append(f"uid:{item['uid']}")
        rows.append(f"{i + 1}. {' | '.join(parts)}")
    text = "\n".join(rows) if rows else "无明细数据"
    if len(text) > _DETAIL_MAX_CHARS:
        return text[:_DETAIL_MAX_CHARS] + "\n…(已截断)"
    return text


def _resolve_url_params(parsed: dict, message: str) -> tuple[str, str, str | None, str | None]:
    """返回 (config_id, biz_type, start_time, end_time)，并写回 detailUrl。"""
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


async def _prepare(
    message: str,
) -> tuple[list, dict, dict, list[str], dict]:
    """返回 (messages, parsed, cls, sources, fetch_meta)。"""
    parsed = parse_alarm_message(message)
    config_id, biz_type, start_time, end_time = _resolve_url_params(parsed, message)

    cls = classify_alarm(parsed)
    playbook = load_playbook(cls["key"])
    system_prompt = (playbook or "") + "\n\n" + _OUTPUT_FORMAT

    fetch_meta: dict[str, Any] = {"fetch_channel": "text_fallback", "config_id": config_id}
    res = None
    if config_id:
        res = await fetch_monitor_data(
            market_config_id=config_id,
            biz_type=biz_type,
            start_time=start_time,
            end_time=end_time,
        )

    rate = (res or {}).get("monitorRate") or {}
    name = rate.get("name") or parsed.get("indicator") or "未知"
    count = rate.get("count") if rate.get("count") is not None else parsed.get("current")
    yesterday = (
        rate.get("yesterdayCount")
        if rate.get("yesterdayCount") is not None
        else parsed.get("yesterdayValue")
    )
    last_week = (
        rate.get("lastWeekCount")
        if rate.get("lastWeekCount") is not None
        else parsed.get("lastWeekValue")
    )

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
    if res:
        fetch_meta["fetch_channel"] = res.get("channel") or "mcp"
        detail_text = _format_detail_for_llm(res.get("monitorDetail"))
        user_prompt += f"\n错误明细（经 MCP 拉取）：\n{detail_text}\n"
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
    sources.append(f"channel:{fetch_meta['fetch_channel']}")
    return messages, parsed, cls, sources, fetch_meta


def _result_dict(
    reply: str,
    parsed: dict,
    cls: dict,
    sources: list[str],
    fetch_meta: dict | None = None,
) -> dict:
    meta = {
        "skill_key": cls.get("key"),
        "config_id": parsed.get("configId"),
        "detail_url": parsed.get("detailUrl") or "",
        "skill_type": cls.get("type"),
        "fetch_channel": (fetch_meta or {}).get("fetch_channel", "text_fallback"),
    }
    return {
        "reply": reply,
        "intent": "alarm",
        "sources": sources,
        "engine": "alarm",
        "cache_hit": False,
        "meta": meta,
    }


async def run_alarm_agent(message: str) -> dict:
    """非流式：供 JSON /chat、Crew Tool 使用。"""
    messages, parsed, cls, sources, fetch_meta = await _prepare(message)
    llm = _build_llm()
    response = await ainvoke_with_retry(llm.ainvoke, messages)
    reply = response.content if hasattr(response, "content") else str(response)
    return _result_dict(reply, parsed, cls, sources, fetch_meta)


async def run_alarm_agent_stream(message: str) -> AsyncIterator[dict]:
    """流式：先发 stage，再拉数+LLM token，最后 done。"""
    yield {
        "type": "stage",
        "stage": "alarm_fetch",
        "msg": "正在解析告警并尝试经 MCP 拉取监控数据…",
        "ok": True,
    }
    messages, parsed, cls, sources, fetch_meta = await _prepare(message)
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
    full_reply = ""
    async for chunk in llm.astream(messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        full_reply += token
        yield {"type": "token", "content": token, "sources": sources}
    yield {"type": "done", **_result_dict(full_reply, parsed, cls, sources, fetch_meta)}
