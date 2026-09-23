"""H3-5：PolicyRegistry / PolicySet 与 Runtime 可选注入。"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.harness.contracts import (
    RUN_COMPLETED,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.policies import PolicySet
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


def test_register_default_policies_only_default():
    reg = register_default_policies()
    assert reg.list_names() == ["default"]
    assert isinstance(reg.get("default"), PolicySet)


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
async def test_runtime_unknown_policy_set_raises():
    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=1)

    reg = PolicyRegistry()
    reg.register("default", PolicySet())
    runtime = AgentRuntime(
        FakeExecutor(),
        policy_registry=reg,
        policy_set="missing",
    )
    with pytest.raises(ValueError, match="not registered"):
        await runtime.execute(RunRequest(input="hi"))
