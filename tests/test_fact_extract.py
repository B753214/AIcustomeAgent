"""Memory-M4-2：事实抽取 Schema 与过滤。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.schema.memory_fact import MemoryFactCandidate, MemoryFactExtractResult
from app.services.memory.fact_extract import extract_and_filter, extract_fact_candidates


def test_candidate_schema_ok():
    c = MemoryFactCandidate.model_validate(
        {
            "kind": "profile",
            "normalized_key": "display_name",
            "content": "用户叫小明",
            "confidence": 0.9,
            "source_type": "explicit",
        }
    )
    assert c.kind == "profile"
    assert c.sensitive is False


def test_candidate_rejects_extra_and_bad_kind():
    with pytest.raises(ValidationError):
        MemoryFactCandidate.model_validate(
            {
                "kind": "profile",
                "normalized_key": "k",
                "content": "x",
                "extra": 1,
            }
        )
    with pytest.raises(ValidationError):
        MemoryFactCandidate.model_validate(
            {
                "kind": "weather",
                "normalized_key": "k",
                "content": "下雨",
            }
        )


@pytest.mark.asyncio
async def test_extract_failure_returns_empty(caplog):
    with (
        patch(
            "app.services.memory.fact_extract.get_llm",
            side_effect=RuntimeError("no llm"),
        ),
        caplog.at_level("WARNING", logger="airobot.memory"),
    ):
        out = await extract_fact_candidates(
            [{"role": "user", "content": "我叫小明"}]
        )
    assert out == []
    assert any("fact extract failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_extract_and_filter_drops_weather_keeps_name():
    fake = MemoryFactExtractResult(
        facts=[
            MemoryFactCandidate(
                kind="business_fact",
                normalized_key="today_weather",
                content="今天北京下雨",
                confidence=0.99,
                source_type="explicit",
            ),
            MemoryFactCandidate(
                kind="profile",
                normalized_key="display_name",
                content="用户叫小明",
                confidence=0.95,
                source_type="explicit",
            ),
        ]
    )

    with patch(
        "app.services.memory.fact_extract.extract_fact_candidates",
        new_callable=AsyncMock,
        return_value=list(fake.facts),
    ):
        kept = await extract_and_filter(
            [
                {"role": "user", "content": "今天天气怎么样，另外我叫小明请记住"},
            ]
        )

    assert len(kept) == 1
    assert kept[0].normalized_key == "display_name"
    assert "小明" in kept[0].content
