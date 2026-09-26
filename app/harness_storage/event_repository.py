from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness.contracts import RunEvent
from app.harness_storage.models import HarnessRunEvent


async def append_event(session: AsyncSession, ev: RunEvent) -> HarnessRunEvent | None:
    """追加事件到 run 事件流；internal 不入库。"""
    if ev.visibility == "internal":
        return None

    ts = ev.timestamp
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)

    row = HarnessRunEvent(
        run_id=ev.run_id,
        sequence=ev.sequence,
        type=ev.type,
        payload=ev.payload or {},
        visibility=ev.visibility,
        timestamp=ts,
    )
    session.add(row)
    await session.flush()
    return row


async def list_events(session: AsyncSession, run_id: str) -> list[HarnessRunEvent]:
    """按 sequence 升序列出某 Run 的事件。"""
    stmt = (
        select(HarnessRunEvent)
        .where(HarnessRunEvent.run_id == run_id)
        .order_by(HarnessRunEvent.sequence)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_events_by_run_ids(
    session: AsyncSession,
    run_ids: list[str],
) -> int:
    """级联删除：按 run_id 列表删其全部 event。"""
    if not run_ids:
        return 0
    stmt = delete(HarnessRunEvent).where(HarnessRunEvent.run_id.in_(run_ids))
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)