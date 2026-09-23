"""H3-1：AgentRegistry 注册 / 获取 / 列表。"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.harness.contracts import RunContext, RunEvent, RUN_COMPLETED
from app.harness.registry.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    get_builtin_agent_registry,
    register_builtin_agents,
)


class FakeExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=1)


def _chat_defn() -> AgentDefinition:
    return AgentDefinition(
        id="chat",
        executor=FakeExecutor(),
        version="1.0",
        prompt_version="1.0",
        tool_allowlist=["query_order"],
        model_roles={"worker": "default"},
        policy_set="chat_default",
    )


def test_register_and_get():
    registry = AgentRegistry()
    defn = _chat_defn()
    registry.register(defn.id, defn)

    got = registry.get("chat")
    assert got is defn
    assert got.id == "chat"
    assert got.version == "1.0"
    assert got.tool_allowlist == ["query_order"]
    assert got.policy_set == "chat_default"
    assert hasattr(got.executor, "astream")


def test_list_ids():
    registry = AgentRegistry()
    registry.register("chat", _chat_defn())
    registry.register(
        "alarm",
        AgentDefinition(id="alarm", executor=FakeExecutor()),
    )
    assert set(registry.list_ids()) == {"chat", "alarm"}


def test_get_unknown_raises():
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="not found"):
        registry.get("nope")


def test_register_duplicate_raises():
    registry = AgentRegistry()
    registry.register("chat", _chat_defn())
    with pytest.raises(ValueError, match="already registered"):
        registry.register("chat", _chat_defn())


def test_register_id_mismatch_raises():
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="does not match"):
        registry.register("wrong", _chat_defn())


def test_register_builtin_agents_ids():
    registry = register_builtin_agents(AgentRegistry())
    assert set(registry.list_ids()) == {"chat", "knowledge", "alarm"}
    assert hasattr(registry.get("chat").executor, "astream")
    assert hasattr(registry.get("knowledge").executor, "astream")
    assert hasattr(registry.get("alarm").executor, "astream")


def test_get_builtin_agent_registry_is_singleton():
    a = get_builtin_agent_registry()
    b = get_builtin_agent_registry()
    assert a is b
    assert set(a.list_ids()) == {"chat", "knowledge", "alarm"}
