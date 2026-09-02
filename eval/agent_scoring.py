"""Pure scoring and report helpers for agent evaluations.

This module intentionally does not import application code. It can be tested and
used to score captured/replayed outputs without LLM, database, or network access.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            case_id = str(case.get("id") or "").strip()
            agent = str(case.get("agent") or "").strip()
            if not case_id or not agent or "input" not in case:
                raise ValueError(f"{path}:{line_no}: id/agent/input are required")
            if case_id in seen:
                raise ValueError(f"{path}:{line_no}: duplicate id {case_id!r}")
            if not isinstance(case.get("expected", {}), dict):
                raise ValueError(f"{path}:{line_no}: expected must be an object")
            seen.add(case_id)
            cases.append(case)
    return cases


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _normal_set(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def score_case(case: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") or {}
    checks: list[dict[str, Any]] = []
    hard_names = _normal_set(expected.get("hard_checks"))

    def add(name: str, passed: bool, weight: float, detail: str, *, hard: bool = False) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "weight": weight,
                "hard": hard,
                "detail": detail,
            }
        )

    for path, wanted in (expected.get("exact") or {}).items():
        got = _get_path(actual, path)
        add(
            f"exact:{path}",
            got == wanted,
            2.0,
            f"expected={wanted!r}, actual={got!r}",
            hard=path in hard_names or f"exact:{path}" in hard_names,
        )

    if "tools" in expected:
        wanted_tools = _normal_set(expected.get("tools"))
        actual_tools = _normal_set(actual.get("tools"))
        add(
            "tools:exact",
            actual_tools == wanted_tools,
            3.0,
            f"expected={sorted(wanted_tools)}, actual={sorted(actual_tools)}",
            hard="tools" in hard_names or "tools:exact" in hard_names,
        )

    text = str(actual.get("reply") or "")
    for phrase in expected.get("required_all") or []:
        phrase = str(phrase)
        add(f"reply:required:{phrase}", phrase in text, 1.0, f"required phrase {phrase!r}")

    required_any = [str(item) for item in expected.get("required_any") or []]
    if required_any:
        add(
            "reply:required_any",
            any(item in text for item in required_any),
            1.0,
            f"one of {required_any!r}",
        )

    for phrase in expected.get("forbidden") or []:
        phrase = str(phrase)
        add(
            f"reply:forbidden:{phrase}",
            phrase not in text,
            2.0,
            f"forbidden phrase {phrase!r}",
            hard=True,
        )

    actual_sources = _normal_set(actual.get("sources"))
    for source in expected.get("sources_contains") or []:
        source = str(source)
        add(
            f"source:{source}",
            any(source in item for item in actual_sources),
            1.0,
            f"source containing {source!r}",
        )

    if "tool_error" in expected:
        got_error = bool(actual.get("tool_error"))
        wanted_error = bool(expected["tool_error"])
        add(
            "tool_error",
            got_error == wanted_error,
            2.0,
            f"expected={wanted_error}, actual={got_error}",
            hard="tool_error" in hard_names,
        )

    if "max_tool_calls" in expected:
        count = int(actual.get("tool_call_count") or 0)
        maximum = int(expected["max_tool_calls"])
        add("tools:max_calls", count <= maximum, 1.0, f"max={maximum}, actual={count}")

    if "min_judge_score" in expected:
        got_score = float(actual.get("judge_score") or 0)
        minimum = float(expected["min_judge_score"])
        add("judge:min_score", got_score >= minimum, 2.0, f"min={minimum}, actual={got_score}")

    if actual.get("error"):
        add("run:no_error", False, 3.0, str(actual["error"]), hard=True)

    if not checks:
        add("case:has_expectations", False, 1.0, "case has no automated expectations", hard=True)

    total_weight = sum(item["weight"] for item in checks)
    passed_weight = sum(item["weight"] for item in checks if item["passed"])
    score = round(100 * passed_weight / total_weight, 2) if total_weight else 0.0
    hard_failed = any(item["hard"] and not item["passed"] for item in checks)
    threshold = float(case.get("pass_threshold", 80))
    return {
        "score": score,
        "passed": score >= threshold and not hard_failed,
        "hard_failed": hard_failed,
        "pass_threshold": threshold,
        "checks": checks,
    }


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 2)


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(1 for row in rows if row["grading"]["passed"])
    hard_failed = sum(1 for row in rows if row["grading"]["hard_failed"])
    scores = [float(row["grading"]["score"]) for row in rows]
    latencies = [float(row["actual"].get("latency_ms") or 0) for row in rows]

    intent_rows = [
        row
        for row in rows
        if "intent" in ((row["case"].get("expected") or {}).get("exact") or {})
    ]
    intent_correct = sum(
        1
        for row in intent_rows
        if row["actual"].get("intent")
        == row["case"]["expected"]["exact"]["intent"]
    )

    tp = fp = fn = 0
    for row in rows:
        expected = row["case"].get("expected") or {}
        if "tools" not in expected:
            continue
        wanted = _normal_set(expected.get("tools"))
        got = _normal_set(row["actual"].get("tools"))
        tp += len(wanted & got)
        fp += len(got - wanted)
        fn += len(wanted - got)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    tool_f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )

    return {
        "cases": count,
        "passed": passed,
        "pass_rate": round(passed / count, 4) if count else 0.0,
        "hard_failures": hard_failed,
        "avg_score": round(sum(scores) / count, 2) if count else 0.0,
        "intent_accuracy": round(intent_correct / len(intent_rows), 4) if intent_rows else None,
        "tool_precision": round(precision, 4) if precision is not None else None,
        "tool_recall": round(recall, 4) if recall is not None else None,
        "tool_f1": round(tool_f1, 4) if tool_f1 is not None else None,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def build_report(
    rows: list[dict[str, Any]], *, dataset: str, repeats: int
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["case"]["agent"]].append(row)
    return {
        "meta": {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "dataset": dataset,
            "runs": len(rows),
            "repeats": repeats,
        },
        "overall": _group_summary(rows),
        "by_agent": {agent: _group_summary(items) for agent, items in sorted(grouped.items())},
        "failures": [
            {
                "id": row["case"]["id"],
                "agent": row["case"]["agent"],
                "repeat": row["repeat"],
                "score": row["grading"]["score"],
                "failed_checks": [
                    check
                    for check in row["grading"]["checks"]
                    if not check["passed"]
                ],
            }
            for row in rows
            if not row["grading"]["passed"]
        ],
        "samples": rows,
    }


def write_report(report: dict[str, Any], out: Path) -> tuple[Path, Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    lines = ["# Agent 评测报告", ""]
    meta = report["meta"]
    lines.extend(
        [
            f"- 时间：{meta['timestamp']}",
            f"- 数据集：{meta['dataset']}",
            f"- 运行数：{meta['runs']}（每条重复 {meta['repeats']} 次）",
            "",
            "## 总览",
            "",
            "| Agent | 样本 | 通过率 | 平均分 | 硬失败 | Intent Acc | Tool F1 | P95(ms) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for agent, item in report["by_agent"].items():
        def show(value: Any) -> str:
            return "-" if value is None else str(value)

        lines.append(
            f"| {agent} | {item['cases']} | {item['pass_rate']:.2%} | "
            f"{item['avg_score']} | {item['hard_failures']} | "
            f"{show(item['intent_accuracy'])} | {show(item['tool_f1'])} | "
            f"{show(item['latency_p95_ms'])} |"
        )
    lines.extend(["", "## 失败样本", ""])
    if not report["failures"]:
        lines.append("无。")
    else:
        for failure in report["failures"]:
            details = "; ".join(item["name"] for item in failure["failed_checks"])
            lines.append(
                f"- `{failure['id']}` / {failure['agent']} / 第 {failure['repeat']} 次："
                f"{failure['score']} 分；{details}"
            )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out, md
