from __future__ import annotations

from app.agents.harness_alarm.executor import AlarmExecutor
from app.harness.contracts import RunRequest, RunResult
from app.harness.runtime import AgentRuntime


def to_run_request(message: str) -> RunRequest:
    """HTTP message → Harness RunRequest。"""
    return RunRequest(
        input=message,
        agent_id="alarm",
        caller="api",
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
