"""Memory-M2-3：sources 摘要落库辅助函数。"""
from __future__ import annotations

from app.services.chat import _summarize_sources, _turn_metadata


def test_summarize_sources_strings_and_dicts():
    assert _summarize_sources(
        ["退货政策#1", {"title": "运费说明", "uri": "http://x"}, {"uri": "only-uri"}]
    ) == ["退货政策#1", "运费说明", "only-uri"]


def test_summarize_sources_limit_and_truncate():
    long = "x" * 500
    out = _summarize_sources([long, "b", "c"], limit=2)
    assert len(out) == 2
    assert out[0] == "x" * 200
    assert out[1] == "b"


def test_turn_metadata_empty_is_none():
    assert _turn_metadata({"sources": []}) is None
    assert _turn_metadata({}) is None
    assert _turn_metadata(None) is None


def test_turn_metadata_with_sources():
    assert _turn_metadata({"sources": ["a#1"]}) == {"sources": ["a#1"]}
    assert _turn_metadata(sources=["b"]) == {"sources": ["b"]}
