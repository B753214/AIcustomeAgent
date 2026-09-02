"""Agent evaluation scoring tests; no application services are called."""
from __future__ import annotations

import json

from eval.agent_scoring import build_report, load_cases, score_case, write_report


def test_load_cases_validates_and_reads_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps({"id": "x-1", "agent": "chat", "input": "hi", "expected": {}})
        + "\n",
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert cases[0]["id"] == "x-1"


def test_score_case_checks_intent_tools_and_reply():
    case = {
        "id": "chat-1",
        "agent": "chat",
        "input": "查订单",
        "expected": {
            "exact": {"intent": "order"},
            "tools": ["query_order"],
            "required_all": ["已发货"],
            "forbidden": ["未查询"],
        },
    }
    actual = {
        "intent": "order",
        "tools": ["query_order", "query_order"],
        "reply": "订单已发货",
    }
    grading = score_case(case, actual)
    assert grading["passed"] is True
    assert grading["score"] == 100.0


def test_forbidden_phrase_is_hard_failure():
    case = {
        "id": "alarm-1",
        "agent": "alarm",
        "input": "alarm",
        "expected": {
            "exact": {"intent": "alarm"},
            "forbidden": ["数据库一定故障"],
        },
    }
    actual = {"intent": "alarm", "reply": "数据库一定故障", "tools": []}
    grading = score_case(case, actual)
    assert grading["hard_failed"] is True
    assert grading["passed"] is False


def test_nested_exact_fields():
    case = {
        "id": "parse-1",
        "agent": "alarm_rule",
        "input": "x",
        "expected": {"exact": {"parsed.configId": "11664", "skill_key": "bff"}},
    }
    actual = {"parsed": {"configId": "11664"}, "skill_key": "bff", "reply": ""}
    assert score_case(case, actual)["score"] == 100.0


def test_report_aggregates_tool_metrics_and_writes_files(tmp_path):
    case = {
        "id": "chat-1",
        "agent": "chat",
        "input": "weather",
        "expected": {"tools": ["query_weather"]},
    }
    actual = {"tools": ["query_weather"], "reply": "晴", "latency_ms": 12.0}
    rows = [
        {
            "case": case,
            "repeat": 1,
            "actual": actual,
            "grading": score_case(case, actual),
        }
    ]
    report = build_report(rows, dataset="cases.jsonl", repeats=1)
    assert report["overall"]["pass_rate"] == 1.0
    assert report["by_agent"]["chat"]["tool_f1"] == 1.0
    json_path, md_path = write_report(report, tmp_path / "report.json")
    assert json_path.exists()
    assert md_path.exists()
    assert "Agent 评测报告" in md_path.read_text(encoding="utf-8")
