"""Memory-M4-6：查看 / 确认 / 修正 / 遗忘（按 fact_id + user）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schema.memory_fact import MemoryFactOut, MemoryFactUpdate
from app.services.memory.fact_store import (
    confirm_fact,
    forget_fact,
    get_fact,
    update_fact,
)


def _row(**kwargs):
    base = {
        "id": "f1",
        "user_id": "u1",
        "tenant_id": None,
        "kind": "profile",
        "normalized_key": "display_name",
        "content": "用户叫小明",
        "confidence": 0.9,
        "source_type": "inferred",
        "status": "candidate",
        "updated_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_get_fact_filters_by_user():
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    out = await get_fact("u-other", "f1", db)
    assert out is None
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_candidate_to_active():
    db = MagicMock()
    db.flush = AsyncMock()
    row = _row(status="candidate")

    with patch(
        "app.services.memory.fact_store.get_fact",
        new_callable=AsyncMock,
        return_value=row,
    ):
        out = await confirm_fact("u1", "f1", db)

    assert out is row
    assert row.status == "active"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_missing_returns_none():
    db = MagicMock()
    with patch(
        "app.services.memory.fact_store.get_fact",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await confirm_fact("u1", "missing", db) is None


@pytest.mark.asyncio
async def test_forget_soft_deletes():
    db = MagicMock()
    db.flush = AsyncMock()
    row = _row(status="active")

    with patch(
        "app.services.memory.fact_store.get_fact",
        new_callable=AsyncMock,
        return_value=row,
    ):
        out = await forget_fact("u1", "f1", db)

    assert out is row
    assert row.status == "deleted"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_same_content_noop():
    db = MagicMock()
    row = _row(content="用户叫小明", status="active")

    with (
        patch(
            "app.services.memory.fact_store.get_fact",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "app.services.memory.fact_store.supersede_fact",
            new_callable=AsyncMock,
        ) as mocked_super,
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
        ) as mocked_insert,
    ):
        out = await update_fact("u1", "f1", "用户叫小明", db)

    assert out is row
    mocked_super.assert_not_awaited()
    mocked_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_content_supersedes():
    db = MagicMock()
    old = _row(content="用户叫小明", status="active")
    new_row = _row(id="f2", content="用户叫小红", status="active")

    with (
        patch(
            "app.services.memory.fact_store.get_fact",
            new_callable=AsyncMock,
            return_value=old,
        ),
        patch(
            "app.services.memory.fact_store.supersede_fact",
            new_callable=AsyncMock,
            return_value=old,
        ) as mocked_super,
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
            return_value=new_row,
        ) as mocked_insert,
    ):
        out = await update_fact("u1", "f1", "用户叫小红", db)

    assert out is new_row
    mocked_super.assert_awaited_once()
    mocked_insert.assert_awaited_once()
    assert mocked_insert.await_args.kwargs["status"] == "active"


def test_memory_fact_out_from_row():
    row = _row(id="abc", normalized_key="display_name")
    dto = MemoryFactOut.from_row(row)
    assert dto.id == "abc"
    assert dto.key == "display_name"
    assert dto.status == "candidate"


def test_memory_fact_update_strips():
    body = MemoryFactUpdate.model_validate({"content": "  hello  "})
    assert body.content == "hello"
