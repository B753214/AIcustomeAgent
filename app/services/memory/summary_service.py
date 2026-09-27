"""滚动摘要：切分 + LLM 结构化输出 + 文本化（M3-4）；失败降级见 M3-5。"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.harness.model import get_llm
from app.schema.memory_summary import SessionSummaryPayload

logger = logging.getLogger("airobot.memory")

_SUMMARY_PROMPT = """根据下列较早的对话消息，生成结构化摘要。
只压缩事实，不编造；字段必须齐全。

消息：
{transcript}
"""


def _turns(messages: list[dict[str, Any]]) -> int:
    return (len(messages) + 1) // 2


def format_summary(summary: SessionSummaryPayload) -> str:
    facts = "；".join(summary.known_facts) or "（无）"
    decisions = "；".join(summary.decisions) or "（无）"
    unresolved = "；".join(summary.unresolved) or "（无）"
    return (
        "【会话摘要】\n"
        f"主题：{summary.topic}\n"
        f"已知事实：{facts}\n"
        f"已做决策：{decisions}\n"
        f"未决问题：{unresolved}"
    )


def _transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role") or "unknown"
        content = (m.get("content") or "").strip()
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def split_for_summary(
    history: list[dict[str, Any]] | None,
    *,
    min_turns: int | None = None,
    keep_turns: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (old_to_summarize, recent_raw)。未达阈值则 old=[]，recent=全量。"""
    msgs = list(history or [])
    min_turns = min_turns if min_turns is not None else settings.memory_summary_min_turns
    keep_turns = keep_turns if keep_turns is not None else settings.memory_summary_keep_turns

    keep_n = max(0, keep_turns) * 2
    if keep_n <= 0 or len(msgs) <= keep_n:
        return [], msgs

    recent = msgs[-keep_n:]
    old = msgs[:-keep_n]
    if _turns(old) < min_turns:
        return [], msgs
    return old, recent


async def summarize_messages(messages: list[dict[str, Any]]) -> SessionSummaryPayload:
    llm = get_llm().with_structured_output(SessionSummaryPayload)
    return await llm.ainvoke(
        _SUMMARY_PROMPT.format(transcript=_transcript(messages))
    )


async def maybe_summarize(
    history: list[dict[str, Any]] | None,
) -> tuple[SessionSummaryPayload | None, list[dict[str, Any]]]:
    """触发则摘要 old，返回 (summary, recent)；失败则 (None, 全量) 不阻断主对话。"""
    old, recent = split_for_summary(history)
    if not old:
        return None, recent
    try:
        summary = await summarize_messages(old)
        return summary, recent
    except Exception as e:
        logger.warning("session summary failed, fallback to truncate: %s", e)
        return None, list(history or [])
