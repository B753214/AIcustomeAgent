"""Memory-M1-5：按 retention 策略清理过期 checkpoint / run / session。

用法：
  python -m app.jobs.memory_retention --dry-run
  python -m app.jobs.memory_retention --limit 200
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.database import AsyncSession as AsyncSessionFactory
from app.harness_storage.checkpoint_repository import (
    count_checkpoints_of_ended_runs,
    delete_checkpoints_of_ended_runs,
)
from app.harness_storage.run_repository import count_expired_runs, delete_expired_runs
from app.jobs.config import (
    retention_checkpoint_days,
    retention_ended_days,
    retention_run_days,
    retention_soft_delete_days,
)
from app.models.sessions import ChatSession

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _session_ids(
    db,
    *,
    where_clauses: tuple,
    limit: int | None,
) -> list[str]:
    stmt = select(ChatSession.session_id).where(*where_clauses)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def _count_sessions(db, *, where_clauses: tuple, limit: int | None) -> int:
    stmt = select(func.count()).select_from(ChatSession).where(*where_clauses)
    total = int((await db.execute(stmt)).scalar_one() or 0)
    if limit is not None:
        return min(total, limit)
    return total


async def _hard_delete_sessions(
    db,
    *,
    where_clauses: tuple,
    limit: int | None,
) -> int:
    ids = await _session_ids(db, where_clauses=where_clauses, limit=limit)
    if not ids:
        return 0
    result = await db.execute(
        delete(ChatSession).where(ChatSession.session_id.in_(ids))
    )
    await db.flush()
    return int(result.rowcount or 0)


async def purge_old_checkpoints(db, dry_run: bool, limit: int | None = None) -> dict:
    """删父 Run 已终态且 ended_at 超期的 checkpoint（limit 暂不切片，整批按 cutoff）。"""
    cutoff = _utcnow_naive() - timedelta(days=retention_checkpoint_days)
    if dry_run:
        n = await count_checkpoints_of_ended_runs(db, cutoff)
        return {"would_delete": n, "cutoff": cutoff.isoformat()}
    deleted = await delete_checkpoints_of_ended_runs(db, cutoff)
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}


async def purge_old_runs(db, dry_run: bool, limit: int | None = None) -> dict:
    """批量删除过期终态 Run（先级联删 checkpoint / event）。"""
    cutoff = _utcnow_naive() - timedelta(days=retention_run_days)
    if dry_run:
        n = await count_expired_runs(db, cutoff, limit=limit)
        return {"would_delete": n, "cutoff": cutoff.isoformat()}
    deleted = await delete_expired_runs(db, cutoff, limit=limit)
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}


async def purge_expired_sessions(db, dry_run: bool, limit: int | None = None) -> dict:
    """会话硬删：ended/archived 按 ended_at+30d；deleted 按 updated_at+7d。"""
    now = _utcnow_naive()
    ended_cutoff = now - timedelta(days=retention_ended_days)
    soft_cutoff = now - timedelta(days=retention_soft_delete_days)

    ended_where = (
        ChatSession.status.in_(("ended", "archived")),
        ChatSession.ended_at.is_not(None),
        ChatSession.ended_at < ended_cutoff,
    )
    soft_where = (
        ChatSession.status == "deleted",
        ChatSession.updated_at < soft_cutoff,
    )

    if dry_run:
        return {
            "ended_archived": {
                "would_delete": await _count_sessions(
                    db, where_clauses=ended_where, limit=limit
                ),
                "cutoff": ended_cutoff.isoformat(),
            },
            "soft_deleted": {
                "would_delete": await _count_sessions(
                    db, where_clauses=soft_where, limit=limit
                ),
                "cutoff": soft_cutoff.isoformat(),
            },
        }

    ended_n = await _hard_delete_sessions(
        db, where_clauses=ended_where, limit=limit
    )
    soft_n = await _hard_delete_sessions(
        db, where_clauses=soft_where, limit=limit
    )
    return {
        "ended_archived": {
            "deleted": ended_n,
            "cutoff": ended_cutoff.isoformat(),
        },
        "soft_deleted": {
            "deleted": soft_n,
            "cutoff": soft_cutoff.isoformat(),
        },
    }


async def run_retention(*, dry_run: bool = False, limit: int = 200) -> dict:
    """顺序：checkpoint → runs/events → sessions。"""
    stats: dict = {"dry_run": dry_run, "limit": limit}
    async with AsyncSessionFactory() as db:
        try:
            stats["checkpoints"] = await purge_old_checkpoints(db, dry_run, limit)
            stats["runs"] = await purge_old_runs(db, dry_run, limit)
            stats["sessions"] = await purge_expired_sessions(db, dry_run, limit)
            if not dry_run:
                await db.commit()
        except Exception:
            if not dry_run:
                await db.rollback()
            raise
    logger.info("memory_retention done: %s", stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memory retention cleanup (M1-5)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计将删数量，不写库",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="每批最多处理条数（runs / sessions）",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(run_retention(dry_run=args.dry_run, limit=args.limit))
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
