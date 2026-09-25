from __future__ import annotations

from typing import AsyncIterator

from app.agents.harness_alarm.executor import AlarmExecutor
from app.database import AsyncSession as session_factory
from app.harness.contracts import RunEvent, RunRequest, RunResult
from app.harness.runtime import AgentRuntime
from app.harness.runtime.cancellation import CancellationToken


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
    return AgentRuntime(AlarmExecutor())


async def alarm_harness_http(message: str) -> dict:
    """JSON alarm：走 Runtime（开关打开时由 main 调用）。"""
    result = await build_alarm_runtime().execute(to_run_request(message))
    return to_alarm_response(result)


def alarm_event_to_sse_dict(ev: RunEvent) -> dict | None:
    """标准 RunEvent → /api/analyze 旧版 SSE chunk；不需要推送的返回 None。"""
    if ev.type == "run.started":
        return None
    if ev.type == "model.token":
        return {"type": "chunk", "content": ev.payload.get("content") or ""}
    if ev.type == "workflow.step":
        return {
            "type": "progress",
            "message": ev.payload.get("message") or "",
        }
    if ev.type == "run.completed":
        meta = dict(ev.payload.get("metadata") or {})
        skip = bool(meta.pop("skip", False))
        payload: dict = {
            "type": "done",
            "run_id": ev.run_id,
            "report": ev.payload.get("output") or "",
            "meta": meta,
        }
        if skip:
            payload["skip"] = True
        return payload
    if ev.type == "run.failed":
        return {
            "type": "error",
            "run_id": ev.run_id,
            "message": (ev.payload or {}).get("message") or "run failed",
        }
    return None


async def alarm_harness_stream(
    message: str,
    *,
    cancellation_token: CancellationToken | None = None,
) -> AsyncIterator[dict]:
    """Alarm SSE：Runtime.execute_stream → /api/analyze 旧 chunk dict。"""
    token = cancellation_token or CancellationToken()
    runtime = build_alarm_runtime()
    async for ev in runtime.execute_stream(
        to_run_request(message, cancellation_token=token)
    ):
        frame = alarm_event_to_sse_dict(ev)
        if frame is not None:
            yield frame
