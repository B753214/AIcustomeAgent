"""标准 RunEvent → SSE wire 帧（H6-3：只出 EVENT_TYPES，不再译旧 token/stage/chunk）。

旧名对照（仅文档，代码不再产出）::

    model.token      ← token / chunk
    workflow.step    ← stage / progress
    run.completed    ← done
    run.failed       ← error
"""
from __future__ import annotations

from app.harness.contracts import RUN_STARTED, RunEvent


def run_event_to_sse_dict(ev: RunEvent) -> dict | None:
    """把 RunEvent 摊平为前端可读的一帧；internal / run.started 默认不推。"""
    if ev.visibility == "internal":
        return None
    if ev.type == RUN_STARTED:
        return None

    frame: dict = {
        "type": ev.type,
        "run_id": ev.run_id,
        "sequence": ev.sequence,
    }
    frame.update(ev.payload or {})
    return frame


# Alarm Adapter / 测试兼容别名（同一函数）
alarm_event_to_sse_dict = run_event_to_sse_dict
