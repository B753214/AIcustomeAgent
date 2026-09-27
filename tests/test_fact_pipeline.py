"""Memory-M4-5：触发启发式、开关、失败降级、auto_active 闸门。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.fact_pipeline import (
    maybe_persist_facts_from_turn,
    should_trigger_fact_extract,
)
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("请记住我叫小明", True),
        ("以后请用简洁回复", True),
        ("今天天气怎么样", False),
        ("帮我查一下订单", False),
    ],
)
def test_should_trigger_heuristic(monkeypatch, text, expected):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "heuristic",
    )
    assert should_trigger_fact_extract(text) is expected


def test_trigger_mode_off(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "off",
    )
    assert should_trigger_fact_extract("请记住我叫小明") is False


def test_trigger_mode_always(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "always",
    )
    assert should_trigger_fact_extract("随便聊一句") is True


@pytest.mark.asyncio
async def test_maybe_persist_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_extract_enabled",
        False,
    )
    with patch(
        "app.services.memory.fact_pipeline.extract_and_filter",
        new_callable=AsyncMock,
    ) as mocked:
        out = await maybe_persist_facts_from_turn(
            "u1", "请记住我叫小明", "好的", MagicMock()
        )
    assert out == []
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_persist_skips_when_no_trigger(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_extract_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "heuristic",
    )
    with patch(
        "app.services.memory.fact_pipeline.extract_and_filter",
        new_callable=AsyncMock,
    ) as mocked:
        out = await maybe_persist_facts_from_turn(
            "u1", "今天天气怎么样", "晴", MagicMock()
        )
    assert out == []
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_persist_happy_path(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_extract_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "heuristic",
    )
    cand = _c()
    row = SimpleNamespace(id="f1", status="active")
    with (
        patch(
            "app.services.memory.fact_pipeline.extract_and_filter",
            new_callable=AsyncMock,
            return_value=[cand],
        ) as mocked_extract,
        patch(
            "app.services.memory.fact_pipeline.persist_prepared_facts",
            new_callable=AsyncMock,
            return_value=[row],
        ) as mocked_persist,
    ):
        out = await maybe_persist_facts_from_turn(
            "u1", "请记住我叫小明", "好的，已记住", MagicMock()
        )

    assert out == [row]
    mocked_extract.assert_awaited_once()
    msgs = mocked_extract.await_args.args[0]
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    mocked_persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_persist_degrades_on_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_extract_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.memory.fact_pipeline.settings.memory_fact_trigger_mode",
        "always",
    )
    with patch(
        "app.services.memory.fact_pipeline.extract_and_filter",
        new_callable=AsyncMock,
        side_effect=RuntimeError("llm down"),
    ):
        out = await maybe_persist_facts_from_turn(
            "u1", "请记住", "ok", MagicMock()
        )
    assert out == []


@pytest.mark.asyncio
async def test_auto_active_false_forces_candidate(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_store.settings.memory_fact_auto_active",
        False,
    )
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
        await upsert_fact_with_supersede("u1", _c(), db)

    assert mocked_insert.await_args.kwargs["status"] == "candidate"


@pytest.mark.asyncio
async def test_min_confidence_active_forces_candidate(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.fact_store.settings.memory_fact_auto_active",
        True,
    )
    monkeypatch.setattr(
        "app.services.memory.fact_store.settings.memory_fact_min_confidence_active",
        0.99,
    )
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
        # policy 对 0.95 explicit 会判 active，但低于配置阈值 → candidate
        await upsert_fact_with_supersede(
            "u1", _c(confidence=0.95), db
        )

    assert mocked_insert.await_args.kwargs["status"] == "candidate"
