"""滚动摘要：切分 + LLM（M3-4）；失败降级（M3-5）；覆盖范围缓存（M3-6）。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.harness.model import get_llm
from app.schema.memory_summary import SessionSummaryPayload
from app.services.memory.summary_store import get_session_summary, upsert_session_summary

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


def _cache_hit(
    *,
    stored_version: str | None,
    through_message_id: str | None,
    old: list[dict[str, Any]],
    prompt_version: str,
) -> bool:
    """version 一致且 through 盖住本次 old 末尾 → 命中。"""
    if not old or not through_message_id:
        return False
    if stored_version != prompt_version:
        return False
    last_id = old[-1].get("id")
    return bool(last_id) and last_id == through_message_id


def _payload_from_stored(summary_json: Any) -> SessionSummaryPayload | None:
    if not isinstance(summary_json, dict):
        return None
    try:
        return SessionSummaryPayload.model_validate(summary_json)
    except Exception as e:
        logger.warning("stored session summary invalid: %s", e)
        return None


async def summarize_messages(messages: list[dict[str, Any]]) -> SessionSummaryPayload:
    llm = get_llm().with_structured_output(SessionSummaryPayload)
    return await llm.ainvoke(
        _SUMMARY_PROMPT.format(transcript=_transcript(messages))
    )


async def maybe_summarize(
    history: list[dict[str, Any]] | None,
    *,
    session_id: str | None = None,
    db: AsyncSession | None = None,
) -> tuple[SessionSummaryPayload | None, list[dict[str, Any]]]:
    """触发则摘要 old；缓存命中跳过 LLM；失败则 (None, 全量)。"""
    old, recent = split_for_summary(history)
    if not old:
        return None, recent

    prompt_version = settings.memory_summary_prompt_version
    can_persist = bool(session_id) and db is not None

    if can_persist:
        row = await get_session_summary(session_id, db)
        if row is not None and _cache_hit(
            stored_version=row.prompt_version,
            through_message_id=row.through_message_id,
            old=old,
            prompt_version=prompt_version,
        ):
            cached = _payload_from_stored(row.summary)
            if cached is not None:
                return cached, recent

    try:
        summary = await summarize_messages(old)
    except Exception as e:
        logger.warning("session summary failed, fallback to truncate: %s", e)
        return None, list(history or [])

    if can_persist:
        try:
            await upsert_session_summary(
                session_id,
                db,
                summary=summary.model_dump(),
                from_message_id=old[0].get("id"),
                through_message_id=old[-1].get("id"),
                prompt_version=prompt_version,
            )
        except Exception as e:
            logger.warning("session summary persist failed: %s", e)

    return summary, recent
