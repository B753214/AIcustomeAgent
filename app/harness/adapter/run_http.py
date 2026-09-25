from __future__ import annotations

from datetime import datetime
from typing import Any

from app.harness_storage import HarnessRun, HarnessRunEvent


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def run_to_dict(row: HarnessRun) -> dict[str, Any]:
    """HarnessRun ORM → JSON 友好 dict（不查库）。"""
    return {
        "run_id": row.run_id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "status": row.status,
        "input": row.input,
        "output": row.output,
        "error": row.error,
        "usage": row.usage,
        "started_at": _dt(row.started_at),
        "ended_at": _dt(row.ended_at),
    }


def event_to_dict(event: HarnessRunEvent) -> dict[str, Any]:
    """HarnessRunEvent ORM → JSON 友好 dict（不查库）。"""
    return {
        "id": event.id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.type,
        "payload": event.payload or {},
        "visibility": event.visibility,
        "timestamp": _dt(event.timestamp),
    }
