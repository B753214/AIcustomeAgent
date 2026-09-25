from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness_storage.models import HarnessCheckpoint


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

