"""长期事实结构化抽取（M4-2）；落库/去重见 M4-3+。"""
from __future__ import annotations

import logging
from typing import Any

from app.harness.model import get_llm
from app.schema.memory_fact import MemoryFactCandidate, MemoryFactExtractResult
from app.services.memory.fact_policy import should_persist_fact

logger = logging.getLogger("airobot.memory")

_EXTRACT_PROMPT = """你是长期事实抽取器。从下列对话中抽出**跨会话仍成立**的事实。

【可记忆 kind】
- profile：稳定身份（如「我叫小明」）
- preference：明确偏好（如「请用简洁中文回复」）
- constraint：硬约束（如「不要打电话联系」）
- business_fact：稳定业务设定（如常用项目代号），不是单次状态

【不可记忆 — 不要输出】
- 天气、气温、新闻
- 单次物流/订单状态、验证码、临时单号
- 模型猜测且用户未确认的偏好
- 一次性请求（翻译、总结这段）

每条必须含：kind、normalized_key（英文蛇形，如 display_name）、content、confidence(0~1)、
source_type（用户明确说请记住→explicit，否则 inferred）、sensitive。
若无可记事实，返回空列表。

对话：
{transcript}
"""


def _transcript(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{m.get('role')}: {(m.get('content') or '').strip()}" for m in messages
    )


async def extract_fact_candidates(
    messages: list[dict[str, Any]] | None,
) -> list[MemoryFactCandidate]:
    """拼 transcript → structured LLM；失败返回 []。"""
    if not messages:
        return []
    try:
        llm = get_llm().with_structured_output(MemoryFactExtractResult)
        result: MemoryFactExtractResult = await llm.ainvoke(
            _EXTRACT_PROMPT.format(transcript=_transcript(messages))
        )
        return list(result.facts or [])
    except Exception as e:
        logger.warning("fact extract failed: %s", e)
        return []


async def extract_and_filter(
    messages: list[dict[str, Any]] | None,
) -> list[MemoryFactCandidate]:
    """抽取后用 M4-1 should_persist_fact 过滤 reject。"""
    candidates = await extract_fact_candidates(messages)
    kept: list[MemoryFactCandidate] = []
    for c in candidates:
        ok, _decision, reason = should_persist_fact(
            kind=c.kind,
            normalized_key=c.normalized_key,
            content=c.content,
            source_type=c.source_type,
            confidence=c.confidence,
            sensitive=c.sensitive,
        )
        if ok:
            kept.append(c)
        else:
            logger.debug("fact filtered out (%s): %s", reason, c.normalized_key)
    return kept
