"""告警 Agent：parse → classify → playbook → LLM 报告。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.load_playbooks import load_playbook
from app.agents.alarm.parse import parse_alarm_message
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


def _prepare(message: str) -> tuple[list, dict, dict, list[str]]:
    """返回 (messages, parsed, cls, sources)。"""
    parsed = parse_alarm_message(message)
    cls = classify_alarm(parsed)
    playbook = load_playbook(cls["key"])
    system_prompt = (playbook or "") + "\n\n" + _OUTPUT_FORMAT
    user_prompt = f"""请分析以下监控告警数据：

监控名称：{parsed.get("indicator") or "未知"}
配置ID：{parsed.get("configId") or "未知"}
当前失败次数：{parsed.get("current") or "未知"}
昨日失败次数：{parsed.get("yesterdayValue") or "未知"}
上周失败次数：{parsed.get("lastWeekValue") or "未知"}
命中规则：{parsed.get("hitRule") or "未知"}
监控链接：{parsed.get("detailUrl") or "无"}
原文：
{message[:1500]}
"""
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    detail_url = parsed.get("detailUrl") or ""
    sources: list[str] = [detail_url] if detail_url else []
    if cls.get("key"):
        sources.append(f"skill:{cls['key']}")
    return messages, parsed, cls, sources


def _result_dict(reply: str, parsed: dict, cls: dict, sources: list[str]) -> dict:
    return {
        "reply": reply,
        "intent": "alarm",
        "sources": sources,
        "engine": "alarm",
        "cache_hit": False,
        "meta": {
            "skill_key": cls.get("key"),
            "config_id": parsed.get("configId"),
            "detail_url": parsed.get("detailUrl") or "",
            "skill_type": cls.get("type"),
        },
    }


async def run_alarm_agent(message: str) -> dict:
    """非流式：供 JSON /chat、Crew Tool 使用。"""
    messages, parsed, cls, sources = _prepare(message)
    llm = _build_llm()
    response = await ainvoke_with_retry(llm.ainvoke, messages)
    reply = response.content if hasattr(response, "content") else str(response)
    return _result_dict(reply, parsed, cls, sources)


async def run_alarm_agent_stream(message: str) -> AsyncIterator[dict]:
    """流式：先发 stage/meta，再逐 token，最后 done（含完整 reply）。"""
    messages, parsed, cls, sources = _prepare(message)
    yield {
        "type": "stage",
        "stage": "alarm",
        "msg": f"告警排查中（{cls.get('type') or cls.get('key') or 'generic'}）",
        "ok": True,
        "meta": {
            "skill_key": cls.get("key"),
            "config_id": parsed.get("configId"),
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
    yield {"type": "done", **_result_dict(full_reply, parsed, cls, sources)}
