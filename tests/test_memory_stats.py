"""Memory-M7-6：事实按 status 计数（Dashboard stats）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.fact_store import count_facts_by_status


@pytest.mark.asyncio
async def test_count_facts_by_status_groups():
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [
        ("active", 3),
        ("candidate", 2),
        ("deleted", 1),
    ]
    db.execute = AsyncMock(return_value=result)

    out = await count_facts_by_status("user-a", db)

    assert out["active"] == 3
    assert out["candidate"] == 2
    assert out["deleted"] == 1
    assert out["superseded"] == 0
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_facts_empty_user():
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    out = await count_facts_by_status("nobody", db)
    assert out == {
        "active": 0,
        "candidate": 0,
        "deleted": 0,
        "superseded": 0,
    }
