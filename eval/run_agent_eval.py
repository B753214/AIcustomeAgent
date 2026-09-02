# -*- coding: utf-8 -*-
"""Unified trajectory evaluation for router, chat, alarm, and Crew agents."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from eval.agent_scoring import build_report, load_cases, score_case, write_report  # noqa: E402

SUPPORTED_AGENTS = {"router", "chat", "alarm_rule", "alarm", "crew"}


def _history_messages(history: list[dict[str, str]]) -> list:
    from langchain_core.messages import AIMessage, HumanMessage

    return [
        HumanMessage(content=item["content"])
        if item.get("role") == "user"
        else AIMessage(content=item["content"])
        for item in history
    ]


async def _run_router(case: dict[str, Any]) -> dict[str, Any]:
    from app.services.chat import classify_intent

    intent = await classify_intent(
        str(case["input"]), _history_messages(case.get("history") or [])
    )
    return {"intent": str(intent), "reply": "", "tools": [], "sources": []}


async def _run_chat(case: dict[str, Any]) -> dict[str, Any]:
    from app.agents.chat_react import run_chat_react

    result = await run_chat_react(
        str(case["input"]), _history_messages(case.get("history") or [])
    )
    meta = result.get("meta") or {}
    tools = list(dict.fromkeys(meta.get("tool_calls") or []))
    return {
        "intent": str(result.get("intent") or ""),
        "reply": str(result.get("reply") or ""),
        "tools": tools,
        "tool_call_count": len(meta.get("tool_calls") or []),
        "tool_error": bool(meta.get("tool_failed")),
        "tool_errors": meta.get("tool_errors") or [],
        "sources": result.get("sources") or [],
        "engine": result.get("engine"),
    }


async def _run_alarm_rule(case: dict[str, Any]) -> dict[str, Any]:
    from app.agents.alarm.classify import classify_alarm
    from app.agents.alarm.detect import detect_input_type, is_alarm_message
    from app.agents.alarm.parse import parse_alarm_message

    message = str(case["input"])
    parsed = parse_alarm_message(message)
    skill = classify_alarm(parsed)
    is_alarm = is_alarm_message(message)
    return {
        "intent": "alarm" if is_alarm else detect_input_type(message),
        "detected_type": detect_input_type(message),
        "is_alarm": is_alarm,
        "parsed": parsed,
        "skill_key": skill.get("key"),
        "skill_type": skill.get("type"),
        "reply": "",
        "tools": [],
        "sources": [],
    }


async def _run_alarm(case: dict[str, Any]) -> dict[str, Any]:
    from app.agents.alarm.runner import run_alarm_agent

    result = await run_alarm_agent(str(case["input"]))
    meta = result.get("meta") or {}
    return {
        "intent": str(result.get("intent") or ""),
        "reply": str(result.get("reply") or ""),
        "tools": [],
        "sources": result.get("sources") or [],
        "skill_key": meta.get("skill_key"),
        "fetch_channel": meta.get("fetch_channel"),
        "replans": meta.get("replans") or [],
        "skip": bool(meta.get("skip")),
        "engine": result.get("engine"),
    }


async def _run_crew(case: dict[str, Any]) -> dict[str, Any]:
    from app.agents.crew import run_crew

    history_text = "\n".join(
        f"{item.get('role')}: {item.get('content')}"
        for item in case.get("history") or []
    )
    result = await run_crew(str(case["input"]), history_text)
    return {
        "intent": str(result.get("intent") or ""),
        "reply": str(result.get("reply") or ""),
        "tools": result.get("tools") or [],
        "sources": result.get("sources") or [],
        "engine": "crew",
    }


RUNNERS = {
    "router": _run_router,
    "chat": _run_chat,
    "alarm_rule": _run_alarm_rule,
    "alarm": _run_alarm,
    "crew": _run_crew,
}


async def run_one(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        actual = await RUNNERS[case["agent"]](case)
    except Exception as exc:
        actual = {
            "reply": "",
            "tools": [],
            "sources": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    actual["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return actual


async def async_main(args: argparse.Namespace) -> int:
    cases = load_cases(Path(args.dataset))
    selected = set(args.agents or SUPPORTED_AGENTS)
    unknown = selected - SUPPORTED_AGENTS
    if unknown:
        raise ValueError(f"unsupported agents: {sorted(unknown)}")
    cases = [
        case
        for case in cases
        if case["agent"] in selected and (args.include_disabled or case.get("enabled", True))
    ]
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("没有匹配的评测样本。")
        return 2

    rows: list[dict[str, Any]] = []
    for repeat in range(1, args.repeat + 1):
        for index, case in enumerate(cases, 1):
            actual = await run_one(case)
            grading = score_case(case, actual)
            rows.append(
                {"case": case, "repeat": repeat, "actual": actual, "grading": grading}
            )
            status = "PASS" if grading["passed"] else "FAIL"
            print(
                f"[{repeat}/{args.repeat}] [{index}/{len(cases)}] "
                f"{status} {case['id']} score={grading['score']} "
                f"latency={actual['latency_ms']}ms"
            )

    report = build_report(rows, dataset=str(Path(args.dataset)), repeats=args.repeat)
    out = (
        Path(args.out)
        if args.out
        else BASE_DIR
        / "eval"
        / "reports"
        / f"agent_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    json_path, md_path = write_report(report, out)
    overall = report["overall"]
    print("\n===== Agent 评测结果 =====")
    print(json.dumps(report["by_agent"], ensure_ascii=False, indent=2))
    print(f"\n报告：{json_path} / {md_path}")
    return 0 if overall["pass_rate"] >= args.fail_under else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Router/Chat/Alarm/Crew 统一评测")
    parser.add_argument(
        "--dataset",
        default=str(BASE_DIR / "eval" / "dataset" / "agent_cases.jsonl"),
    )
    parser.add_argument("--agents", nargs="*", choices=sorted(SUPPORTED_AGENTS))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--fail-under", type=float, default=0.8)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
