from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    AgentExecutor,
    HarnessError,
    RunContext,
    RunEvent,
    RunRequest,
    RunResult,
)
from app.harness.registry import PolicyRegistry
from app.harness.runtime.cancellation import CancellationToken
from app.harness_storage import persist_event, persist_run_end, persist_run_start

_TERMINAL = frozenset({RUN_COMPLETED, RUN_FAILED})


def _cancelled_payload() -> dict[str, Any]:
    return {
        "category": "policy",
        "message": "run cancelled",
        "details": {},
        "cancelled": True,
    }


async def _persist_terminal(
    factory: Any,
    run_id: str,
    ev: RunEvent,
) -> None:
    """终态事件：更新 harness_runs。"""
    if ev.type == RUN_COMPLETED:
        await persist_run_end(
            factory,
            run_id,
            status="succeeded",
            output=ev.payload.get("output") if ev.payload else None,
            usage=ev.payload.get("usage") if ev.payload else None,
        )
    elif ev.type == RUN_FAILED:
        status = "cancelled" if (ev.payload or {}).get("cancelled") else "failed"
        await persist_run_end(
            factory,
            run_id,
            status=status,
            error=dict(ev.payload) if ev.payload else {},
        )


class AgentRuntime:
    """统一开跑门面：建 Run、转发 Executor 事件、归一失败。"""

    def __init__(
        self,
        executor: AgentExecutor,
        *,
        policy_registry: PolicyRegistry | None = None,
        policy_set: str = "default",
    ) -> None:
        self.executor = executor
        self._policy_registry = policy_registry
        self._policy_set = policy_set

    def _apply_pre_policies(self, ctx: RunContext) -> RunContext:
        """Executor 运行前的策略钩子。

        - 未传入 policy_registry：跳过（兼容 AgentRuntime(executor)）。
        - 已传入：按 policy_set 名取 PolicySet 并 apply_before。
        - 策略名未注册：透传 PolicyRegistry.get 的 ValueError。
        """
        if self._policy_registry is None:
            return ctx
        return self._policy_registry.get(self._policy_set).apply_before(ctx)

    async def execute_stream(
        self,
        request: RunRequest,
        *,
        run_id: str | None = None,
    ) -> AsyncIterator[RunEvent]:
        """把一次 RunRequest 变成有序 RunEvent 流。

        SSE / DB 事务约定（H2-5）：
        - Runtime 与 Executor 默认不持有 SQLAlchemy AsyncSession。
        - 禁止用「同一个 session」包住整段 async for 事件推流。
        - 有 options.session_factory 时：每条事件短开短关 persist_*（含 Run 起止）。
        - execute() 只消费本流聚合，不再单独落库。
        """
        run_id = run_id or str(uuid.uuid4())
        options = request.options or {}
        token = options.get("cancellation_token") or CancellationToken()
        ctx = self._apply_pre_policies(
            RunContext(
                run_id=run_id,
                request=request,
                cancellation_token=token,
            )
        )

        options = request.options or {}
        factory = options.get("session_factory")

        await persist_run_start(
            factory,
            run_id=run_id,
            input=request.input,
            agent_id=request.agent_id,
            session_id=request.session_id,
            status="running",
        )

        seq = 0
        started = RunEvent(type=RUN_STARTED, run_id=run_id, sequence=seq)
        await persist_event(factory, started)
        yield started
        seq += 1

        saw_terminal = False
        try:
            async for ev in self.executor.astream(ctx):
                if token.is_cancelled():
                    failed = RunEvent(
                        type=RUN_FAILED,
                        run_id=run_id,
                        sequence=seq,
                        payload=_cancelled_payload(),
                    )
                    await persist_event(factory, failed)
                    await _persist_terminal(factory, run_id, failed)
                    yield failed
                    return

                out = ev.model_copy(update={"run_id": run_id, "sequence": seq})
                if out.type in _TERMINAL:
                    saw_terminal = True
                await persist_event(factory, out)
                if out.type in _TERMINAL:
                    await _persist_terminal(factory, run_id, out)
                yield out
                seq += 1
        except Exception as e:
            err = HarnessError.from_exception(e)
            failed = RunEvent(
                type=RUN_FAILED,
                run_id=run_id,
                sequence=seq,
                payload=err.to_dict(),
            )
            await persist_event(factory, failed)
            await _persist_terminal(factory, run_id, failed)
            yield failed
            return

        if token.is_cancelled():
            failed = RunEvent(
                type=RUN_FAILED,
                run_id=run_id,
                sequence=seq,
                payload=_cancelled_payload(),
            )
            await persist_event(factory, failed)
            await _persist_terminal(factory, run_id, failed)
            yield failed
            return

        if not saw_terminal:
            completed = RunEvent(
                type=RUN_COMPLETED,
                run_id=run_id,
                sequence=seq,
                payload={},
            )
            await persist_event(factory, completed)
            await _persist_terminal(factory, run_id, completed)
            yield completed

    async def execute(self, request: RunRequest) -> RunResult:
        """消费 execute_stream，聚合成一次 RunResult（落库由 stream 侧 persist 完成）。"""
        status: str | None = None
        output: str | None = None
        error: dict[str, Any] | None = None
        sources: list[Any] = []
        usage: dict[str, Any] = {}
        metadata: dict[str, Any] = {}
        output_parts: list[str] = []

        run_id = str(uuid.uuid4())

        async for ev in self.execute_stream(request, run_id=run_id):
            if ev.type == MODEL_TOKEN:
                content = ev.payload.get("content")
                if content:
                    output_parts.append(str(content))
            elif ev.type == RUN_COMPLETED:
                status = "succeeded"
                if ev.payload.get("output") is not None:
                    output = ev.payload.get("output")
                if ev.payload.get("sources") is not None:
                    sources = list(ev.payload.get("sources") or [])
                if ev.payload.get("usage"):
                    usage = dict(ev.payload.get("usage") or {})
                if ev.payload.get("metadata"):
                    metadata = dict(ev.payload.get("metadata") or {})
            elif ev.type == RUN_FAILED:
                if ev.payload.get("cancelled"):
                    status = "cancelled"
                else:
                    status = "failed"
                error = dict(ev.payload) if ev.payload else {}

        if not output and output_parts:
            output = "".join(output_parts)
        if status is None:
            status = "failed"
            error = {
                "category": "internal",
                "message": "missing terminal event",
                "details": {},
            }

        metadata = {**metadata, "run_id": run_id}
        return RunResult(
            status=status,  # type: ignore[arg-type]
            output=output,
            error=error,
            sources=sources,
            usage=usage,
            metadata=metadata,
        )
