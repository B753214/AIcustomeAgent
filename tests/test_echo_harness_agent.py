"""H7-3：echo 玩具 Agent — 只注册、不改 Runtime。"""
from __future__ import annotations

import pytest

from app.harness.contracts import RUN_COMPLETED, RUN_STARTED, RunRequest
from app.harness.registry.agent_registry import AgentRegistry, register_builtin_agents
from app.harness.runtime import AgentRuntime


@pytest.mark.asyncio
async def test_echo_agent_via_registry_and_runtime():
    registry = register_builtin_agents(AgentRegistry())
    defn = registry.get("echo")
    assert defn.id == "echo"

    runtime = AgentRuntime(defn.executor)
    text = "hello echo"
    events = [
        e async for e in runtime.execute_stream(RunRequest(input=text, agent_id="echo"))
    ]

    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_COMPLETED
    assert events[-1].payload.get("output") == text
    assert [e.sequence for e in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_echo_execute_aggregates_output():
    registry = register_builtin_agents(AgentRegistry())
    result = await AgentRuntime(registry.get("echo").executor).execute(
        RunRequest(input="ping", agent_id="echo")
    )
    assert result.status == "succeeded"
    assert result.output == "ping"
    assert result.metadata.get("run_id")
