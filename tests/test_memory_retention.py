"""Memory-M1-5：保留期清理规则单测（不连真库）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs import memory_retention as mr
from app.jobs.config import retention_ended_days, retention_soft_delete_days
from app.models.sessions import ChatSession


@pytest.mark.asyncio
async def test_purge_sessions_dry_run_splits_rules():
    db = AsyncMock()
    counter = AsyncMock(side_effect=[3, 2])
    with patch.object(mr, "_count_sessions", new=counter):
        out = await mr.purge_expired_sessions(db, dry_run=True, limit=200)

    assert out["ended_archived"]["would_delete"] == 3
    assert out["soft_deleted"]["would_delete"] == 2
    assert counter.await_count == 2
    assert "cutoff" in out["ended_archived"]
    assert "cutoff" in out["soft_deleted"]


@pytest.mark.asyncio
async def test_purge_sessions_deletes_two_batches():
    db = AsyncMock()
    with patch.object(
        mr, "_hard_delete_sessions", new=AsyncMock(side_effect=[1, 4])
    ) as hard:
        out = await mr.purge_expired_sessions(db, dry_run=False, limit=50)

    assert out["ended_archived"]["deleted"] == 1
    assert out["soft_deleted"]["deleted"] == 4
    assert hard.await_count == 2
    assert hard.await_args_list[0].kwargs["limit"] == 50
    assert hard.await_args_list[1].kwargs["limit"] == 50
    # 两刀 where 不同：第一刀含 ended_at，第二刀含 updated_at
    assert any("ended_at" in str(c) for c in hard.await_args_list[0].kwargs["where_clauses"])
    assert any("updated_at" in str(c) for c in hard.await_args_list[1].kwargs["where_clauses"])



@pytest.mark.asyncio
async def test_hard_delete_sessions_selects_then_deletes():
    db = AsyncMock()
    id_result = MagicMock()
    id_result.scalars.return_value.all.return_value = ["s1", "s2"]
    del_result = MagicMock()
    del_result.rowcount = 2
    db.execute = AsyncMock(side_effect=[id_result, del_result])
    db.flush = AsyncMock()

    n = await mr._hard_delete_sessions(
        db,
        where_clauses=(ChatSession.status == "deleted",),
        limit=10,
    )
    assert n == 2
    assert db.execute.await_count == 2
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_purge_runs_dry_run_uses_count():
    db = AsyncMock()
    with patch(
        "app.jobs.memory_retention.count_expired_runs",
        new=AsyncMock(return_value=5),
    ):
        out = await mr.purge_old_runs(db, dry_run=True, limit=200)
    assert out["would_delete"] == 5
    assert "cutoff" in out


def test_retention_day_constants_match_policy():
    assert retention_ended_days == 30
    assert retention_soft_delete_days == 7


def test_main_dry_run_parses(monkeypatch):
    called = {}

    async def _fake(**kwargs):
        called.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(mr, "run_retention", _fake)
    code = mr.main(["--dry-run", "--limit", "10"])
    assert code == 0
    assert called == {"dry_run": True, "limit": 10}
