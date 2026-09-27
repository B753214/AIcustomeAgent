"""Memory-M4-3：归一化、批内去重、库内同内容跳过。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.fact_normalize import (
    dedupe_candidates,
    normalize_content,
    normalize_fact_candidate,
    normalize_key,
    prepare_facts_for_upsert,
)


def _c(**kwargs) -> MemoryFactCandidate:
    base = {
        "kind": "profile",
        "normalized_key": "display_name",
        "content": "用户叫小明",
        "confidence": 0.8,
        "source_type": "explicit",
    }
    base.update(kwargs)
    return MemoryFactCandidate.model_validate(base)


def test_normalize_key_variants():
    assert normalize_key("Display Name") == "display_name"
    assert normalize_key("display-name") == "display_name"
    assert normalize_key("___") == ""


def test_normalize_content_whitespace_and_punct():
    assert normalize_content("  用户叫  小明。 ") == "用户叫 小明"


def test_dedupe_merges_key_variants_keeps_higher_confidence():
    batch = [
        _c(normalized_key="Display Name", confidence=0.5, content="叫小明"),
        _c(normalized_key="display_name", confidence=0.9, content="用户叫小明"),
    ]
    out = dedupe_candidates(batch)
    assert len(out) == 1
    assert out[0].normalized_key == "display_name"
    assert out[0].confidence == 0.9
    assert out[0].content == "用户叫小明"


def test_dedupe_drops_empty_key():
    out = dedupe_candidates([_c(normalized_key="!!!")])
    assert out == []


@pytest.mark.asyncio
async def test_prepare_skips_same_content_in_db():
    candidates = [_c(normalized_key="display_name", content="用户叫小明")]
    row = SimpleNamespace(content="用户叫小明。")  # 归一化后相同

    with patch(
        "app.services.memory.fact_normalize.find_active_or_candidate",
        new_callable=AsyncMock,
        return_value=row,
    ):
        out = await prepare_facts_for_upsert("u1", candidates, db=object())

    assert out == []


@pytest.mark.asyncio
async def test_prepare_keeps_when_content_differs():
    candidates = [_c(content="用户叫小红")]
    row = SimpleNamespace(content="用户叫小明")

    with patch(
        "app.services.memory.fact_normalize.find_active_or_candidate",
        new_callable=AsyncMock,
        return_value=row,
    ):
        out = await prepare_facts_for_upsert("u1", candidates, db=object())

    assert len(out) == 1
    assert out[0].content == "用户叫小红"


@pytest.mark.asyncio
async def test_prepare_keeps_when_no_row():
    candidates = [_c()]
    with patch(
        "app.services.memory.fact_normalize.find_active_or_candidate",
        new_callable=AsyncMock,
        return_value=None,
    ):
        out = await prepare_facts_for_upsert("u1", candidates, db=object())
    assert len(out) == 1
