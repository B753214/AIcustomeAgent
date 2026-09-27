"""长期事实归一化与写入前准备（M4-3）。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.fact_store import find_active_or_candidate

_KEY_INVALID_CHARS = re.compile(r"[^a-z0-9_]")
_KEY_MULTI_UNDERSCORE = re.compile(r"_{2,}")
_CONTENT_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[。！？.!?,;:：；\s]+$")


def normalize_key(key: str) -> str:
    s = (key or "").lower().strip()
    s = _KEY_INVALID_CHARS.sub("_", s)
    s = _KEY_MULTI_UNDERSCORE.sub("_", s)
    return s.strip("_")


def normalize_content(content: str, strip_trailing_punct: bool = True) -> str:
    s = (content or "").strip()
    s = _CONTENT_WHITESPACE.sub(" ", s)
    if strip_trailing_punct:
        s = _TRAILING_PUNCT.sub("", s)
    return s.strip()


def normalize_fact_candidate(candidate: MemoryFactCandidate) -> MemoryFactCandidate:
    """归一化单条候选（key + content）；返回新实例。"""
    return candidate.model_copy(
        update={
            "normalized_key": normalize_key(candidate.normalized_key),
            "content": normalize_content(candidate.content),
        }
    )


def dedupe_candidates(
    candidates: list[MemoryFactCandidate],
) -> list[MemoryFactCandidate]:
    """先 normalize，再按 (kind, normalized_key) 去重，只留 confidence 最高。

    confidence 相同时保留先出现的那条；空 key 丢弃。
    """
    best: dict[tuple[str, str], MemoryFactCandidate] = {}
    order: list[tuple[str, str]] = []
    for candidate in candidates:
        c = normalize_fact_candidate(candidate)
        if not c.normalized_key:
            continue
        k = (c.kind, c.normalized_key)
        if k not in best:
            order.append(k)
            best[k] = c
        elif c.confidence > best[k].confidence:
            best[k] = c
    return [best[k] for k in order]


async def prepare_facts_for_upsert(
    user_id: str,
    candidates: list[MemoryFactCandidate],
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> list[MemoryFactCandidate]:
    """normalize → 批内 dedupe → 库内同内容跳过；返回待写入候选。

    库中已有同 key 但 content 不同的条目仍返回（留给 M4-4 supersede）。
    """
    batch = dedupe_candidates(candidates)
    out: list[MemoryFactCandidate] = []
    for c in batch:
        row = await find_active_or_candidate(
            user_id, c.kind, c.normalized_key, db, tenant_id=tenant_id
        )
        if row is not None and normalize_content(row.content) == c.content:
            continue
        out.append(c)
    return out
