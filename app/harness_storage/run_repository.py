from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness_storage.models import HarnessRun

_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_run(
    session: AsyncSession,
    *,
    run_id: str,
    input: str,
    agent_id: str | None = None,
    session_id: str | None = None,
    status: str = "running",
) -> HarnessRun:
    """插入一条 Run（短事务由调用方 commit）。"""
    run = HarnessRun(
        run_id=run_id,
        agent_id=agent_id,
        session_id=session_id,
        status=status,
        input=input,
    )
    session.add(run)
    await session.flush()
    return run


async def update_run(
    session: AsyncSession,
    run_id: str,
    *,
    status: str,
    output: str | None = None,
    error: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    ended_at: datetime | None = None,
) -> HarnessRun | None:
    """更新终态；不存在则返回 None。"""
    run = await session.get(HarnessRun, run_id)
    if run is None:
        return None
    run.status = status
    if output is not None:
        run.output = output
    if error is not None:
        run.error = error
    if usage is not None:
        run.usage = usage
    run.ended_at = ended_at or _utcnow_naive()
    await session.flush()
    return run


async def get_run(session: AsyncSession, run_id: str) -> HarnessRun | None:
    """按 run_id 查询。"""
    return await session.get(HarnessRun, run_id)

def _expired_run_filter(cutoff: datetime):
    return (
        HarnessRun.ended_at < cutoff,
        HarnessRun.status.in_(_TERMINAL_STATUSES),
    )


async def count_expired_runs(
    session: AsyncSession,
    cutoff: datetime,
    *,
    limit: int | None = None,
) -> int:
    """dry-run：统计将被删除的 Run 数（受 limit 上限）。"""
    stmt = select(func.count()).select_from(HarnessRun).where(
        *_expired_run_filter(cutoff)
    )
    total = int((await session.execute(stmt)).scalar_one() or 0)
    if limit is not None:
        return min(total, limit)
    return total


async def delete_expired_runs(
    session: AsyncSession,
    cutoff: datetime,
    *,
    limit: int | None = None,
) -> int:
    """批量删除过期终态 Run。

    PG 不支持 DELETE ... LIMIT，所以先 SELECT run_id LIMIT N，
    再 DELETE WHERE run_id IN (...)。同时级联删 checkpoint 和 event
    （这两张表没有 FK 约束，PG 不会自动级联）。
    """
    from app.harness_storage.checkpoint_repository import delete_checkpoints_by_run_ids
    from app.harness_storage.event_repository import delete_events_by_run_ids

    select_stmt = select(HarnessRun.run_id).where(*_expired_run_filter(cutoff))
    if limit is not None:
        select_stmt = select_stmt.limit(limit)
    result = await session.execute(select_stmt)
    run_ids = list(result.scalars().all())

    if not run_ids:
        return 0

    await delete_checkpoints_by_run_ids(session, run_ids)
    await delete_events_by_run_ids(session, run_ids)

    delete_stmt = delete(HarnessRun).where(HarnessRun.run_id.in_(run_ids))
    await session.execute(delete_stmt)
    await session.flush()
    return len(run_ids)