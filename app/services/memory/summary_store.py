from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sessions import SessionSummary


async def get_session_summary(
    session_id: str,
    db: AsyncSession,
) -> SessionSummary | None:
    stmt = select(SessionSummary).where(SessionSummary.session_id == session_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_session_summary(
    session_id: str,
    db: AsyncSession,
    *,
    summary: dict,
    from_message_id: str | None = None,
    through_message_id: str | None = None,
    prompt_version: str = "v1",
) -> SessionSummary:
    existing = await get_session_summary(session_id, db)
    if existing is not None:
        existing.summary = summary
        existing.from_message_id = from_message_id
        existing.through_message_id = through_message_id
        existing.prompt_version = prompt_version
        await db.flush()
        return existing
    row = SessionSummary(
        session_id=session_id,
        summary=summary,
        from_message_id=from_message_id,
        through_message_id=through_message_id,
        prompt_version=prompt_version,
    )
    db.add(row)
    await db.flush()
    return row