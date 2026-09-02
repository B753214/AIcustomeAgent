"""Chat-ReAct-Day1：活动 Mock 工具。"""
from __future__ import annotations

from app.agents.activity import match_activities, query_activity


def test_query_activity_all_on_empty_or_generic():
    text = query_activity("最近有什么活动")
    assert "新人专享" in text
    assert "周末免运费" in text
    assert "双十一" in text
    assert "为你找到" in text


def test_query_activity_newbie():
    text = query_activity("新人有什么优惠")
    assert "新人专享满减" in text
    assert "满 50 减 20" in text
    assert "以旧换新" not in text


def test_query_activity_weekend():
    hits = match_activities("周末包邮")
    assert len(hits) == 1
    assert hits[0]["id"] == "weekend"


def test_query_activity_no_match():
    text = query_activity("航天火箭门票")
    assert "暂无相关活动" in text
