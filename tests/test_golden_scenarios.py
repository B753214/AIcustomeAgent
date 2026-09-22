"""H0-6：黄金场景清单校验 + 可离线断言部分。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.detect import detect_input_type, is_alarm_message
from app.agents.alarm.parse import parse_alarm_message
from app.agents.tools import query_order

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
AGENTS = ("chat", "knowledge", "alarm")


def _load(name: str) -> list[dict]:
    path = GOLDEN_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def test_manifest_and_min_cases():
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["min_cases_per_agent"] >= 2
    for agent in AGENTS:
        filename = manifest["files"][agent]
        cases = _load(filename)
        assert len(cases) >= manifest["min_cases_per_agent"], agent
        for case in cases:
            assert case["agent"] == agent
            assert case["id"]
            assert case["input"]
            assert "expected" in case
            assert "route" in case


@pytest.mark.parametrize("case", _load("chat.json"), ids=lambda c: c["id"])
def test_chat_offline_hooks(case):
    offline = (case.get("expected") or {}).get("offline") or {}
    if offline.get("direct_tool") != "query_order":
        return
    text = query_order(offline.get("tool_input") or case["input"])
    prefix = offline.get("must_not_start_with")
    if prefix:
        assert not text.startswith(prefix), text
    for token in offline.get("required_all") or []:
        assert token in text


@pytest.mark.parametrize("case", _load("knowledge.json"), ids=lambda c: c["id"])
def test_knowledge_offline_hooks(case):
    offline = (case.get("expected") or {}).get("offline") or {}
    if "is_alarm_message" in offline:
        assert is_alarm_message(case["input"]) is offline["is_alarm_message"]
    kb = (case.get("expected") or {}).get("kb_hint") or {}
    corpus = kb.get("corpus")
    section = kb.get("section")
    if corpus and section:
        root = Path(__file__).resolve().parents[1]
        text = (root / corpus).read_text(encoding="utf-8")
        assert section in text


@pytest.mark.parametrize("case", _load("alarm.json"), ids=lambda c: c["id"])
def test_alarm_offline_hooks(case):
    offline = (case.get("expected") or {}).get("offline") or {}
    if not offline:
        return
    if "is_alarm_message" in offline:
        assert is_alarm_message(case["input"]) is offline["is_alarm_message"]
    if "detected_type" in offline:
        assert detect_input_type(case["input"]) == offline["detected_type"]
    parsed_exp = offline.get("parsed") or {}
    if parsed_exp:
        parsed = parse_alarm_message(case["input"])
        for key, value in parsed_exp.items():
            assert parsed.get(key) == value
    skill = offline.get("skill_key")
    if skill:
        parsed = parse_alarm_message(case["input"])
        assert classify_alarm(parsed)["key"] == skill
