"""Memory-M4-4：冲突 supersede 与写入。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.fact_store import upsert_fact_with_supersede


def _c(**kwargs) -> MemoryFactCandidate:
    base = {
        "kind": "profile",
        "normalized_key": "display_name",
        "content": "用户叫小明",
        "confidence": 0.95,
        "source_type": "explicit",
    }
    base.update(kwargs)
    return MemoryFactCandidate.model_validate(base)


@pytest.mark.asyncio
async def test_upsert_inserts_when_no_old():
    db = MagicMock()
    new_row = SimpleNamespace(id="n1", content="用户叫小明", status="active")

    with (
        patch(
            "app.services.memory.fact_store.find_active_or_candidate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
            return_value=new_row,
        ) as mocked_insert,
        patch(
            "app.services.memory.fact_store.supersede_fact",
            new_callable=AsyncMock,
        ) as mocked_super,
    ):
        out = await upsert_fact_with_supersede("u1", _c(), db)

    assert out is new_row
    mocked_insert.assert_awaited_once()
    mocked_super.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_returns_old_when_same_content():
    db = MagicMock()
    old = SimpleNamespace(content="用户叫小明。", status="active")

    with (
        patch(
            "app.services.memory.fact_store.find_active_or_candidate",
            new_callable=AsyncMock,
            return_value=old,
        ),
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
        ) as mocked_insert,
        patch(
            "app.services.memory.fact_store.supersede_fact",
            new_callable=AsyncMock,
        ) as mocked_super,
    ):
        out = await upsert_fact_with_supersede(
            "u1", _c(content="用户叫小明"), db
        )

    assert out is old
    mocked_insert.assert_not_awaited()
    mocked_super.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_supersedes_when_content_differs():
    db = MagicMock()
    old = SimpleNamespace(content="用户叫小明", status="active")
    new_row = SimpleNamespace(content="用户叫小红", status="active")

    with (
        patch(
            "app.services.memory.fact_store.find_active_or_candidate",
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
        out = await upsert_fact_with_supersede(
            "u1", _c(content="用户叫小红"), db
        )

    assert out is new_row
    mocked_super.assert_awaited_once()
    mocked_insert.assert_awaited_once()
    assert mocked_insert.await_args.kwargs["status"] == "active"


@pytest.mark.asyncio
async def test_upsert_inferred_writes_candidate():
    db = MagicMock()
    new_row = SimpleNamespace(status="candidate")

    with (
        patch(
            "app.services.memory.fact_store.find_active_or_candidate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
            return_value=new_row,
        ) as mocked_insert,
    ):
        await upsert_fact_with_supersede(
            "u1",
            _c(source_type="inferred", confidence=0.9, content="似乎喜欢简洁"),
            db,
        )

    assert mocked_insert.await_args.kwargs["status"] == "candidate"
