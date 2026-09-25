"""H3-5 / H6-2：PolicyRegistry、PolicySet 与 Runtime 策略失败 → run.failed。"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.harness.contracts import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.policies import AuthPolicy, BudgetPolicy, PolicySet, TimeoutPolicy
from app.harness.registry import PolicyRegistry, register_default_policies
from app.harness.runtime import AgentRuntime


def test_register_get_and_list():
    reg = PolicyRegistry()
    ps = PolicySet()
    reg.register("default", ps)
    assert reg.get("default") is ps
    assert reg.list_names() == ["default"]


def test_duplicate_and_missing():
    reg = PolicyRegistry()
    reg.register("default", PolicySet())
    with pytest.raises(ValueError, match="already registered"):
        reg.register("default", PolicySet())
    with pytest.raises(ValueError, match="not registered"):
        reg.get("nope")


def test_apply_before_noop():
    ctx = RunContext(run_id="r1", request=RunRequest(input="hi"))
    out = PolicySet().apply_before(ctx)
    assert out is ctx
    assert PolicySet().apply_after(ctx, result=None) is None


def test_register_default_policies_wires_real_policies():
    reg = register_default_policies()
    assert set(reg.list_names()) == {"default", "strict"}
    default = reg.get("default")
    assert default._auth is not None
    assert default._budget is not None
    assert default._budget.max_tool_calls == 20
    assert default._timeout is not None
    strict = reg.get("strict")
    assert strict._budget.max_tool_calls == 0


def test_caller_can_apply_before_without_runtime():
    class MarkerPolicy(PolicySet):
        def apply_before(self, ctx: RunContext) -> RunContext:
            ctx.metadata["policy_hit"] = True
            return ctx

    reg = PolicyRegistry()
    reg.register("default", MarkerPolicy())
    ctx = RunContext(run_id="r1", request=RunRequest(input="hi"))
    ctx = reg.get("default").apply_before(ctx)
    assert ctx.metadata.get("policy_hit") is True


@pytest.mark.asyncio
async def test_runtime_injects_policy_before_executor():
    class MarkerPolicy(PolicySet):
        def apply_before(self, ctx: RunContext) -> RunContext:
            ctx.metadata["policy_hit"] = True
            return ctx

    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            assert ctx.metadata.get("policy_hit") is True
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"output": "ok"},
            )

    reg = PolicyRegistry()
    reg.register("default", MarkerPolicy())
    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=reg,
        policy_set="default",
    )
    result = await runtime.execute(RunRequest(input="hi"))
    assert result.status == "succeeded"
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_runtime_without_policy_registry_still_works():
    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"output": "plain"},
            )

    result = await AgentRuntime(FakeExecutor()).execute(RunRequest(input="hi"))
    assert result.output == "plain"


@pytest.mark.asyncio
async def test_runtime_unknown_policy_set_becomes_run_failed():
    """未注册 policy_set 名：不再向外抛，而是 run.failed。"""

    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            raise AssertionError("不应进入 Executor")
            yield  # pragma: no cover

    reg = PolicyRegistry()
    reg.register("default", PolicySet())
    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=reg,
        policy_set="missing",
    )
    events = [
        ev async for ev in runtime.execute_stream(RunRequest(input="hi"))
    ]
    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert "not registered" in (events[-1].payload or {}).get("message", "")


@pytest.mark.asyncio
async def test_runtime_budget_zero_yields_policy_failed():
    called = {"n": 0}

    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            called["n"] += 1
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"output": "should-not"},
            )

    reg = PolicyRegistry()
    reg.register(
        "tight",
        PolicySet(
            auth=AuthPolicy(allowlist={"api"}),
            budget=BudgetPolicy(max_tool_calls=0),
            timeout=TimeoutPolicy(run_seconds=30),
        ),
    )
    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=reg,
        policy_set="tight",
    )
    events = [
        ev
        async for ev in runtime.execute_stream(
            RunRequest(input="hi", caller="api")
        )
    ]
    assert called["n"] == 0
    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert events[-1].payload["category"] == HarnessErrorCategory.POLICY.value
    assert "tool_calls" in events[-1].payload["message"]


@pytest.mark.asyncio
async def test_runtime_bad_caller_yields_policy_failed():
    called = {"n": 0}

    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            called["n"] += 1
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"output": "nope"},
            )

    reg = register_default_policies()
    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=reg,
        policy_set="default",
    )
    events = [
        ev
        async for ev in runtime.execute_stream(
            RunRequest(input="hi", caller="evil")
        )
    ]
    assert called["n"] == 0
    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert events[-1].payload["category"] == HarnessErrorCategory.POLICY.value


@pytest.mark.asyncio
async def test_runtime_strict_policy_set_fails():
    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"output": "x"},
            )

    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=register_default_policies(),
        policy_set="strict",
    )
    result = await runtime.execute(RunRequest(input="hi", caller="api"))
    assert result.status == "failed"
    assert (result.error or {}).get("category") == "policy"
