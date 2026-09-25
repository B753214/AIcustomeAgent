from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.harness.contracts import RunEvent
from app.harness_storage.checkpoint_repository import load_checkpoint, save_checkpoint
from app.harness_storage.event_repository import append_event
from app.harness_storage.run_repository import create_run, update_run

SessionFactory = async_sessionmaker[AsyncSession]


async def persist_run_start(
    factory: SessionFactory | None,
    *,
    run_id: str,
    input: str,
    agent_id: str | None = None,
    session_id: str | None = None,
    status: str = "running",
) -> None:
    """短事务插入一条 Run 台账。"""
    if factory is None:
        return
    async with factory() as session:
        await create_run(
            session,
            run_id=run_id,
            input=input,
            agent_id=agent_id,
            session_id=session_id,
            status=status,
        )
        await session.commit()


async def persist_run_end(
    factory: SessionFactory | None,
    run_id: str,
    *,
    status: str,
    output: str | None = None,
    error: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """短事务更新 Run 终态。"""
    if factory is None:
        return
    async with factory() as session:
        await update_run(
            session,
            run_id,
            status=status,
            output=output,
            error=error,
            usage=usage,
        )
        await session.commit()


async def persist_event(factory: SessionFactory | None, ev: RunEvent) -> None:
    """短事务追加一条 RunEvent（internal 由 append_event 跳过）。"""
    if factory is None:
        return
    async with factory() as session:
        await append_event(session, ev)
        await session.commit()


async def persist_checkpoint(
    factory: SessionFactory | None,
    run_id: str,
    name: str,
    payload: dict[str, Any],
) -> None:
    """短事务 upsert 检查点。"""
    if factory is None:
        return
    async with factory() as session:
        await save_checkpoint(session, run_id, name, payload)
        await session.commit()


async def persist_load_checkpoint(
    factory: SessionFactory | None,
    run_id: str,
    name: str,
) -> dict[str, Any] | None:
    """短事务读取检查点 payload；不存在或无 factory 返回 None。"""
    if factory is None:
        return None
    async with factory() as session:
        row = await load_checkpoint(session, run_id, name)
        if row is None:
            return None
        return dict(row.payload or {})
