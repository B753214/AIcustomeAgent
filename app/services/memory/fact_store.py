"""长期事实读写（M4-3/M4-4）：查找、插入、supersede。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.memory_facts import MemoryFact
from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.fact_policy import should_persist_fact

logger = logging.getLogger("airobot.memory")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def find_active_or_candidate(
    user_id: str,
    kind: str,
    key: str,
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> MemoryFact | None:
    """按 user + kind + normalized_key 查找 active/candidate 事实。"""
    from app.services.memory.fact_normalize import normalize_key

    key_n = normalize_key(key)
    if not key_n:
        return None
    cond = [
        MemoryFact.user_id == user_id,
        MemoryFact.kind == kind,
        MemoryFact.normalized_key == key_n,
        MemoryFact.status.in_(("active", "candidate")),
    ]
    if tenant_id is None:
        cond.append(MemoryFact.tenant_id.is_(None))
    else:
        cond.append(MemoryFact.tenant_id == tenant_id)
    stmt = select(MemoryFact).where(*cond).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def supersede_fact(old: MemoryFact, db: AsyncSession) -> MemoryFact:
    """将旧事实标为 superseded（不 commit，由外层会话提交）。"""
    old.status = "superseded"
    old.updated_at = _utcnow_naive()
    await db.flush()
    return old


async def insert_fact(
    user_id: str,
    candidate: MemoryFactCandidate,
    *,
    status: str,
    db: AsyncSession,
    tenant_id: str | None = None,
    source_message_id: str | None = None,
) -> MemoryFact:
    """插入新 MemoryFact 行。"""
    from app.services.memory.fact_normalize import normalize_content, normalize_key

    row = MemoryFact(
        user_id=user_id,
        tenant_id=tenant_id,
        kind=candidate.kind,
        normalized_key=normalize_key(candidate.normalized_key),
        content=normalize_content(candidate.content),
        confidence=candidate.confidence,
        source_type=candidate.source_type,
        source_message_id=source_message_id,
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


def _resolve_status(candidate: MemoryFactCandidate) -> str | None:
    ok, decision, reason = should_persist_fact(
        kind=candidate.kind,
        normalized_key=candidate.normalized_key,
        content=candidate.content,
        source_type=candidate.source_type,
        confidence=candidate.confidence,
        sensitive=candidate.sensitive,
    )
    if not ok:
        logger.debug("skip insert (%s): %s", reason, candidate.normalized_key)
        return None
    if decision == "active":
        if not settings.memory_fact_auto_active:
            return "candidate"
        if candidate.confidence < settings.memory_fact_min_confidence_active:
            return "candidate"
    return decision


async def upsert_fact_with_supersede(
    user_id: str,
    candidate: MemoryFactCandidate,
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
    source_message_id: str | None = None,
) -> MemoryFact | None:
    """同 key：同内容返回旧行；不同则 supersede 旧行并插入新行。"""
    from app.services.memory.fact_normalize import (
        normalize_content,
        normalize_fact_candidate,
    )

    c = normalize_fact_candidate(candidate)
    status = _resolve_status(c)
    if status is None:
        return None

    old = await find_active_or_candidate(
        user_id, c.kind, c.normalized_key, db, tenant_id=tenant_id
    )
    if old is not None:
        if normalize_content(old.content) == c.content:
            return old
        await supersede_fact(old, db)

    return await insert_fact(
        user_id,
        c,
        status=status,
        db=db,
        tenant_id=tenant_id,
        source_message_id=source_message_id,
    )


async def persist_prepared_facts(
    user_id: str,
    candidates: list[MemoryFactCandidate],
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> list[MemoryFact]:
    """对 prepare_facts_for_upsert 的结果逐条 upsert。"""
    from app.services.memory.fact_normalize import prepare_facts_for_upsert

    prepared = await prepare_facts_for_upsert(
        user_id, candidates, db, tenant_id=tenant_id
    )
    saved: list[MemoryFact] = []
    for c in prepared:
        row = await upsert_fact_with_supersede(
            user_id, c, db, tenant_id=tenant_id
        )
        if row is not None:
            saved.append(row)
    return saved

async def list_facts(
    user_id: str,
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[MemoryFact]:
    """列出当前用户 live 事实（默认 active+candidate）。"""
    limit = max(1, min(int(limit or 50), 200))
    cond = [MemoryFact.user_id == user_id]
    if status is None:
        cond.append(MemoryFact.status.in_(("active", "candidate")))
    elif status in ("active", "candidate"):
        cond.append(MemoryFact.status == status)
    else:
        return []
    stmt = (
        select(MemoryFact)
        .where(*cond)
        .order_by(MemoryFact.updated_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_fact(
    user_id: str,
    fact_id: str,
    db: AsyncSession,
) -> MemoryFact | None:
    """按 id + user 取 live 事实；非本人或不存在 → None。"""
    stmt = select(MemoryFact).where(
        MemoryFact.id == fact_id,
        MemoryFact.user_id == user_id,
        MemoryFact.status.in_(("active", "candidate")),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def confirm_fact(
    user_id: str,
    fact_id: str,
    db: AsyncSession,
) -> MemoryFact | None:
    """candidate → active；已是 active 原样返回。"""
    row = await get_fact(user_id, fact_id, db)
    if row is None:
        return None
    if row.status == "active":
        return row
    if row.status != "candidate":
        return None
    row.status = "active"
    row.updated_at = _utcnow_naive()
    await db.flush()
    return row


async def update_fact(
    user_id: str,
    fact_id: str,
    content: str,
    db: AsyncSession,
) -> MemoryFact | None:
    """修正 content：相同则返回原行；不同则 supersede + 插入（保留原 status）。"""
    from app.services.memory.fact_normalize import normalize_content

    row = await get_fact(user_id, fact_id, db)
    if row is None:
        return None
    new_content = normalize_content(content)
    if not new_content:
        return None
    if normalize_content(row.content) == new_content:
        return row

    keep_status = row.status
    tenant_id = row.tenant_id
    kind = row.kind
    key = row.normalized_key
    conf = row.confidence
    await supersede_fact(row, db)
    return await insert_fact(
        user_id,
        MemoryFactCandidate.model_validate(
            {
                "kind": kind,
                "normalized_key": key,
                "content": new_content,
                "confidence": max(float(conf or 0.0), 0.9),
                "source_type": "explicit",
            }
        ),
        status=keep_status,
        db=db,
        tenant_id=tenant_id,
    )


async def forget_fact(
    user_id: str,
    fact_id: str,
    db: AsyncSession,
) -> MemoryFact | None:
    """软删：status=deleted。"""
    row = await get_fact(user_id, fact_id, db)
    if row is None:
        return None
    row.status = "deleted"
    row.updated_at = _utcnow_naive()
    await db.flush()
    return row
