from __future__ import annotations

from typing import Any

from app.agents.alarm.classify import classify_alarm
from app.agents.alarm.detect import detect_input_type, is_alarm_message
from app.agents.alarm.load_playbooks import load_playbook
from app.agents.alarm.parse import parse_alarm_message

__all__ = [
    "detect_input_type",
    "is_alarm_message",
    "parse_alarm_message",
    "load_playbook",
    "classify_alarm",
    "run_alarm_agent",
    "run_alarm_agent_stream",
    "resolve_analyze_url",
]


def __getattr__(name: str) -> Any:
    """重依赖（langchain）按需加载，避免纯规则单测被拖垮。"""
    if name == "resolve_analyze_url":
        from app.agents.alarm.chat_intent import resolve_analyze_url

        return resolve_analyze_url
    if name == "run_alarm_agent":
        from app.agents.alarm.runner import run_alarm_agent

        return run_alarm_agent
    if name == "run_alarm_agent_stream":
        from app.agents.alarm.runner import run_alarm_agent_stream

        return run_alarm_agent_stream
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
