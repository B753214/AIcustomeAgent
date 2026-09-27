"""Memory-M6-A：Alarm episode merge / extract 纯函数。"""
from __future__ import annotations

from app.services.memory.alarm_episode import (
    extract_episode_from_alarm_result,
    merge_alarm_followup,
)


def test_merge_without_card_returns_message():
    assert merge_alarm_followup("看第 2 页", {}) == "看第 2 页"
    assert merge_alarm_followup("看第 2 页", None) == "看第 2 页"


def test_merge_includes_config_and_url():
    text = merge_alarm_followup(
        "看第 2 页",
        {
            "config_id": "11664",
            "monitor_url": "https://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664",
            "metric": "填单BFF",
            "level": "P1",
            "page": 1,
        },
    )
    assert "【配置ID】：11664" in text
    assert "marketConfigId=11664" in text
    assert "【会话追问】看第 2 页" in text
    assert "【指标】：填单BFF" in text
    assert "【情景页码】1" in text


def test_extract_from_alarm_result():
    ep = extract_episode_from_alarm_result(
        {
            "reply": "排查结论…" + ("x" * 600),
            "meta": {
                "config_id": "11664",
                "detail_url": "https://info-plate.fc.alibaba-inc.com/x",
                "page_count": 2,
                "skill_key": "blank",
            },
        }
    )
    assert ep["config_id"] == "11664"
    assert ep["monitor_url"].startswith("https://")
    assert ep["page"] == 2
    assert ep["playbook_hint"] == "blank"
    assert len(ep["evidence_summary"]) == 500


def test_extract_empty_without_keys():
    assert extract_episode_from_alarm_result({"meta": {}, "reply": "x"}) == {}
    assert extract_episode_from_alarm_result(None) == {}
