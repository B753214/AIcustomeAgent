"""Day10：无监控链接时，用 LLM 从自然语言抽 analyze URL（对齐 car_robot CHAT_SYSTEM_PROMPT）。"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.services.resilience import ainvoke_with_retry

CHAT_SYSTEM_PROMPT = """你是智能运维 Agent 助手中的前端页面报警分析模块，负责排查 info-plate 监控告警。

你的能力：
1. 分析 info-plate 监控链接中的告警数据（前端页面/BFF/渲染/AJX/VOC 等）
2. 回答关于报警排查、监控、前端错误的专业问题
3. 友好地回答其他问题（完整闲聊与知识库问答由主助手其他通道处理）

重要规则：
- 如果用户消息中包含监控参数（bizType、marketConfigId），并且有时间信息或说了"最近X小时/分钟"，你需要提取参数并构造链接。
  输出格式严格为一行 JSON（不要加其他文字）：
  {"action":"analyze","url":"https://info-plate.fc.alibaba-inc.com/monitor/searchall?bizType={bizType}&marketConfigId={marketConfigId}&startTime={毫秒时间戳}&endTime={毫秒时间戳}"}
  时间计算规则："最近1小时"= endTime为当前时间戳, startTime为endTime-3600000
- 如果用户发的消息中包含 info-plate 链接但你不确定是否完整，直接告诉用户把完整链接发过来
- 如果是排查相关问题，用专业知识简洁回答
- 如果是闲聊，友好简短回复
- 回复不要使用 markdown 格式符号（不要用 ## ** 等）"""

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_ANALYZE_ACTION_RE = re.compile(
    r'\{"action"\s*:\s*"analyze"\s*,\s*"url"\s*:\s*"([^"]+)"\}'
)

_FALLBACK_CHAT = "抱歉，我暂时无法回复。你可以直接发送 info-plate 监控链接给我分析。"


def strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def extract_analyze_url_from_reply(text: str) -> str | None:
    """从 LLM 回复中解析 analyze action 的 url；没有则返回 None。"""
    cleaned = strip_think(text)
    m = _ANALYZE_ACTION_RE.search(cleaned)
    return m.group(1) if m else None


def _build_llm():
    return init_chat_model(
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        model=settings.AIROBOT_LLM_MODEL,
        model_provider=settings.provider,
    )


def _user_prompt(content: str) -> str:
    now = datetime.now(timezone.utc)
    ms = int(now.timestamp() * 1000)
    return f"当前时间：{now.isoformat()}（毫秒时间戳：{ms}）\n\n用户消息：{content}"


def _messages(content: str) -> list:
    return [
        SystemMessage(content=CHAT_SYSTEM_PROMPT),
        HumanMessage(content=_user_prompt(content)),
    ]


def _split_result(full: str) -> tuple[str | None, str | None]:
    """(url, chat_reply)。有 url 时 chat_reply 为 None。"""
    cleaned = strip_think(full)
    url = extract_analyze_url_from_reply(cleaned)
    if url:
        return url, None
    return None, cleaned or _FALLBACK_CHAT


async def resolve_analyze_url(content: str) -> tuple[str | None, str | None]:
    """(url, chat_reply)。有 url 则拉数；仅闲聊则 chat_reply 非空。"""
    try:
        llm = _build_llm()
        response = await ainvoke_with_retry(llm.ainvoke, _messages(content))
        text = getattr(response, "content", None) or str(response)
        return _split_result(text)
    except Exception:
        return None, _FALLBACK_CHAT


async def iter_resolve_analyze_url(content: str) -> AsyncIterator[dict[str, Any]]:
    """供 SSE 使用：先 yield token，再 yield result（url / chat_reply）。"""
    try:
        llm = _build_llm()
        parts: list[str] = []
        async for chunk in llm.astream(_messages(content)):
            piece = getattr(chunk, "content", None) or ""
            if not piece:
                continue
            parts.append(piece)
            yield {"type": "token", "content": piece}
        url, chat_reply = _split_result("".join(parts))
        yield {"type": "result", "url": url, "chat_reply": chat_reply}
    except Exception as e:
        yield {"type": "error", "message": f"AI 回复失败: {e}"}
