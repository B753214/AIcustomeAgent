"""告警 Agent：detect / parse / classify 单测（不调 LLM / MCP）。"""
from __future__ import annotations

import pytest

from app.agents.alarm.classify import classify_alarm, classify_by_name
from app.agents.alarm.detect import detect_input_type, is_alarm_message
from app.agents.alarm.parse import extract_monitor_url, parse_alarm_message

_URL = (
    "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
    "?marketConfigId=11664&bizType=30"
)
_FIELDS = "P1 【指标】：填单BFF失败\n【配置ID】：11664\n【命中规则】：失败次数超阈"
_BOTH = f"{_FIELDS}\n{_URL}"


# ── detect ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expect",
    [
        (_BOTH, True),
        (_FIELDS, False),
        (_URL, False),
        ("七天无理由退货怎么申请？", False),
        ("什么是 P1 告警？", False),
        ("", False),
    ],
)
def test_is_alarm_message_requires_fields_and_url(text, expect):
    assert is_alarm_message(text) is expect


def test_detect_input_type_sides():
    assert detect_input_type(_BOTH) == "alarm"
    assert detect_input_type(_FIELDS) == "alarm"
    assert detect_input_type(_URL) == "url"
    assert detect_input_type("你好") == "unknown"


# ── parse ───────────────────────────────────────────────


def test_parse_alarm_message_extracts_config_and_url():
    parsed = parse_alarm_message(_BOTH)
    assert parsed["configId"] == "11664"
    assert parsed["indicator"] == "填单BFF失败"
    assert parsed["level"] == "P1"
    assert "info-plate.fc.alibaba-inc.com" in parsed["detailUrl"]
    assert "marketConfigId=11664" in parsed["detailUrl"]


def test_extract_monitor_url():
    assert extract_monitor_url(_URL) == _URL
    assert extract_monitor_url("无链接文本") is None


# ── classify ────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, key",
    [
        ("填单BFF失败", "bff"),
        ("页面白屏", "render"),
        ("AJX报错监控", "ajx"),
        ("VOC舆情", "voc"),
        ("随便一个名字", "precise"),
    ],
)
def test_classify_by_name(name, key):
    result = classify_by_name(name)
    assert result["type"] == {
        "bff": "BFF错误",
        "render": "渲染异常",
        "ajx": "AJX报错",
        "voc": "VOC",
        "precise": "精准报警",
    }[key]


def test_classify_alarm_uses_indicator():
    out = classify_alarm({"indicator": "填单BFF", "business": "", "hitRule": ""})
    assert out["key"] == "bff"
    assert "skill" in out
    assert out["type"] == "BFF错误"


def test_classify_alarm_explicit_skips_name_inference():
    """有【类型】等显式分类时，不再按指标名推断。"""
    out = classify_alarm(
        {
            "alarmType": "BFF",
            "indicator": "页面白屏监控",  # 若走名称会判 render
            "business": "",
            "hitRule": "",
        }
    )
    assert out["key"] == "bff"
    assert out["type"] == "BFF错误"


def test_classify_alarm_explicit_type_label():
    out = classify_alarm({"alarmType": "渲染异常", "indicator": "填单BFF"})
    assert out["key"] == "render"


def test_parse_alarm_type_field():
    from app.agents.alarm.parse import parse_alarm_message

    text = "P1 【指标】：页面白屏\n【类型】：BFF\n【配置ID】：1"
    parsed = parse_alarm_message(text)
    assert parsed["alarmType"] == "BFF"
    assert classify_alarm(parsed)["key"] == "bff"
