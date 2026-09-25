from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.harness_storage.models import HarnessRun


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
