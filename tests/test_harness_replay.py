"""H7-1 Replay：录制标准事件序列 → JSON 回放，不花真钱。"""
from __future__ import annotations

import json
from typing import AsyncIterator

import pytest

from app.harness.contracts import (
    EVENT_TYPES,
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_STARTED,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.runtime import AgentRuntime

# 录好的一次成功轨迹（仅 type + payload；run_id/sequence 由 Runtime 覆盖）
_RECORDED_TRACE = [
    {"type": MODEL_TOKEN, "payload": {"content": "你"}},
    {"type": MODEL_TOKEN, "payload": {"content": "好"}},
    {"type": RUN_COMPLETED, "payload": {"output": "你好"}},
]


class ReplayExecutor:
    """按录制轨迹吐事件，模拟「离线重放模型/工具响应」。"""

    def __init__(self, trace: list[dict]) -> None:
        self._trace = trace

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        for item in self._trace:
            yield RunEvent(
                type=item["type"],
                run_id=ctx.run_id,
                sequence=0,
                payload=dict(item.get("payload") or {}),
            )


def test_recorded_trace_roundtrip_json():
    """轨迹可 JSON 序列化再还原，且 type 均在 EVENT_TYPES。"""
    blob = json.dumps(_RECORDED_TRACE, ensure_ascii=False)
    restored = json.loads(blob)
    assert restored == _RECORDED_TRACE
    for item in restored:
        assert item["type"] in EVENT_TYPES


@pytest.mark.asyncio
async def test_replay_executor_through_runtime():
    """Runtime 消费回放轨迹 → 标准序列；事件可再 JSON 化。"""
    runtime = AgentRuntime(ReplayExecutor(_RECORDED_TRACE))
    events = [
        e async for e in runtime.execute_stream(RunRequest(input="replay"))
    ]

    assert events[0].type == RUN_STARTED
    assert [e.type for e in events[1:]] == [t["type"] for t in _RECORDED_TRACE]
    assert [e.sequence for e in events] == list(range(len(events)))
    assert events[-1].type == RUN_COMPLETED
    assert events[-1].payload.get("output") == "你好"

    wire = [e.model_dump(mode="json") for e in events]
    blob = json.dumps(wire, ensure_ascii=False)
    restored = [RunEvent.model_validate(row) for row in json.loads(blob)]
    assert [e.type for e in restored] == [e.type for e in events]
    assert restored[-1].payload.get("output") == "你好"
