from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness_storage.models import HarnessCheckpoint, HarnessRun


_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _ended_run_id_subq(cutoff: datetime):
    return select(HarnessRun.run_id).where(
        HarnessRun.ended_at < cutoff,
        HarnessRun.status.in_(_TERMINAL_STATUSES),
    )


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def save_checkpoint(
    session: AsyncSession,
    run_id: str,
    name: str,
    payload: dict[str, Any],
) -> HarnessCheckpoint:
    """按 (run_id, name) upsert 检查点。"""
    cp = await session.get(HarnessCheckpoint, (run_id, name))
    if cp is None:
        cp = HarnessCheckpoint(run_id=run_id, name=name, payload=payload)
        session.add(cp)
    else:
        cp.payload = payload
        cp.updated_at = _utcnow_naive()
    await session.flush()
    return cp


async def load_checkpoint(
    session: AsyncSession,
    run_id: str,
    name: str,
) -> HarnessCheckpoint | None:
    """加载指定检查点。"""
    return await session.get(HarnessCheckpoint, (run_id, name))


async def list_checkpoints(
    session: AsyncSession,
    run_id: str,
) -> list[HarnessCheckpoint]:
    """列出某 Run 下全部检查点。"""
    stmt = select(HarnessCheckpoint).where(HarnessCheckpoint.run_id == run_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())

async def count_checkpoints_of_ended_runs(
    session: AsyncSession,
    cutoff: datetime,
) -> int:
    """dry-run：统计将被删除的 checkpoint 行数。"""
    stmt = (
        select(func.count())
        .select_from(HarnessCheckpoint)
        .where(HarnessCheckpoint.run_id.in_(_ended_run_id_subq(cutoff)))
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


async def delete_checkpoints_of_ended_runs(
    session: AsyncSession,
    cutoff: datetime,
) -> int:
    """删除其父 Run 已终态且 ended_at < cutoff 的全部检查点。

    对齐策略：checkpoint 是否过期不看自身 updated_at，而是看所属 Run
    是否已经结束（succeeded/failed/cancelled）且 ended_at 超阈值。
    这样正在跑的 run 即使 checkpoint 写得很早也不会被误删。
    """
    stmt = delete(HarnessCheckpoint).where(
        HarnessCheckpoint.run_id.in_(_ended_run_id_subq(cutoff))
    )
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


async def delete_checkpoints_by_run_ids(
    session: AsyncSession,
    run_ids: list[str],
) -> int:
    """级联删除：按 run_id 列表删其全部 checkpoint（供 run 删除流程调用）。"""
    if not run_ids:
        return 0
    stmt = delete(HarnessCheckpoint).where(HarnessCheckpoint.run_id.in_(run_ids))
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)