"""H6-4：Runtime 落库 / SSE 下发前脱敏。"""
from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.policies import DataPolicy
from app.harness.registry import register_default_policies
from app.harness.runtime import AgentRuntime

SECRET = "sk-ABCDEFGHIJKLMNOPQRSTUV"


class SecretTokenExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type=MODEL_TOKEN,
            run_id=ctx.run_id,
            sequence=0,
            payload={"content": f"key={SECRET}"},
        )
        yield RunEvent(
            type=RUN_COMPLETED,
            run_id=ctx.run_id,
            sequence=1,
            payload={
                "output": f"done password=secret999 {SECRET}",
                "metadata": {"note": f"Bearer {SECRET}xxxx"},
            },
        )


class SecretBoomExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise RuntimeError(f"upstream leaked {SECRET}")
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_execute_stream_redacts_secrets_in_yield_and_persist():
    persisted: list[RunEvent] = []

    async def capture_persist(_factory: Any, ev: RunEvent) -> None:
        persisted.append(ev)

    runtime = AgentRuntime(
        SecretTokenExecutor(),
        policy_registry=register_default_policies(),
        policy_set="default",
    )
    with (
        patch(
            "app.harness.runtime.agent_runtime.persist_run_start",
            new=AsyncMock(),
        ),
        patch(
            "app.harness.runtime.agent_runtime.persist_event",
            new=capture_persist,
        ),
        patch(
            "app.harness.runtime.agent_runtime.persist_run_end",
            new=AsyncMock(),
        ),
    ):
        events = [
            e async for e in runtime.execute_stream(RunRequest(input="hi"))
        ]

    token_ev = next(e for e in events if e.type == MODEL_TOKEN)
    done_ev = next(e for e in events if e.type == RUN_COMPLETED)
    assert SECRET not in (token_ev.payload.get("content") or "")
    assert SECRET not in (done_ev.payload.get("output") or "")
    assert "secret999" not in (done_ev.payload.get("output") or "")

    # 落库事件同样无明文
    stored_blob = " ".join(
        str((e.payload or {}).get("content") or "")
        + str((e.payload or {}).get("output") or "")
        + str((e.payload or {}).get("metadata") or "")
        for e in persisted
    )
    assert SECRET not in stored_blob
    assert "secret999" not in stored_blob

    # sanitize 后再断言无残留明文规则命中
    DataPolicy().assert_no_secrets(token_ev.payload)
    DataPolicy().assert_no_secrets(done_ev.payload)


@pytest.mark.asyncio
async def test_execute_stream_redacts_failed_exception_message():
    persisted: list[RunEvent] = []

    async def capture_persist(_factory: Any, ev: RunEvent) -> None:
        persisted.append(ev)

    runtime = AgentRuntime(SecretBoomExecutor())
    with (
        patch(
            "app.harness.runtime.agent_runtime.persist_run_start",
            new=AsyncMock(),
        ),
        patch(
            "app.harness.runtime.agent_runtime.persist_event",
            new=capture_persist,
        ),
        patch(
            "app.harness.runtime.agent_runtime.persist_run_end",
            new=AsyncMock(),
        ),
    ):
        events = [
            e async for e in runtime.execute_stream(RunRequest(input="hi"))
        ]

    assert events[0].type == RUN_STARTED
    failed = events[-1]
    assert failed.type == RUN_FAILED
    assert SECRET not in (failed.payload.get("message") or "")
    assert SECRET not in str(failed.payload.get("details") or {})
    DataPolicy().assert_no_secrets(failed.payload)
