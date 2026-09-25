from __future__ import annotations

from typing import AsyncIterator

from app.agents.harness_alarm.executor import AlarmExecutor
from app.database import AsyncSession as session_factory
from app.harness.adapter.sse_map import (
    alarm_event_to_sse_dict,
    run_event_to_sse_dict,
)
from app.harness.contracts import RunRequest, RunResult
from app.harness.registry import register_default_policies
from app.harness.runtime import AgentRuntime
from app.harness.runtime.cancellation import CancellationToken

__all__ = [
    "alarm_event_to_sse_dict",
    "alarm_harness_http",
    "alarm_harness_stream",
    "build_alarm_runtime",
    "to_alarm_response",
    "to_run_request",
]


def to_run_request(
    message: str,
    *,
    cancellation_token: CancellationToken | None = None,
) -> RunRequest:
    """HTTP message → Harness RunRequest。"""
    options: dict = {"session_factory": session_factory}
    if cancellation_token is not None:
        options["cancellation_token"] = cancellation_token
    return RunRequest(
        input=message,
        agent_id="alarm",
        caller="api",
        options=options,
    )


def to_alarm_response(result: RunResult) -> dict:
    """Harness RunResult → /api/v1/alarm 响应形状。"""
    meta = dict(result.metadata or {})
    sources: list = []
    for item in result.sources or []:
        if isinstance(item, str):
            sources.append(item)
        elif isinstance(item, dict):
            sources.append(item.get("title") or item.get("uri") or str(item))
        else:
            sources.append(str(item))
    out: dict = {
        "reply": result.output or "",
        "sources": sources,
        "intent": meta.get("intent"),
        "engine": meta.get("engine", "alarm"),
    }
    if result.error:
        out["error"] = result.error
    return out


def build_alarm_runtime() -> AgentRuntime:
    return AgentRuntime(
        AlarmExecutor(),
        policy_registry=register_default_policies(),
        policy_set="default",
    )


async def alarm_harness_http(message: str) -> dict:
    """JSON alarm：走 Runtime（开关打开时由 main 调用）。"""
    result = await build_alarm_runtime().execute(to_run_request(message))
    return to_alarm_response(result)


async def alarm_harness_stream(
    message: str,
    *,
    cancellation_token: CancellationToken | None = None,
) -> AsyncIterator[dict]:
    """Alarm SSE：Runtime.execute_stream → 标准 RunEvent 帧。"""
    token = cancellation_token or CancellationToken()
    runtime = build_alarm_runtime()
    async for ev in runtime.execute_stream(
        to_run_request(message, cancellation_token=token)
    ):
        frame = run_event_to_sse_dict(ev)
        if frame is not None:
            yield frame
