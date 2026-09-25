from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    AgentExecutor,
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
    RunRequest,
    RunResult,
)
from app.harness.policies import DataPolicy
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
        - 策略名未注册：ValueError 在 execute_stream 的 try 内被捕获，变为 run.failed。
        """
        if self._policy_registry is None:
            return ctx
        return self._policy_registry.get(self._policy_set).apply_before(ctx)

    def _data_policy(self) -> DataPolicy:
        if self._policy_registry is None:
            return DataPolicy()
        try:
            ps = self._policy_registry.get(self._policy_set)
        except ValueError:
            return DataPolicy()
        return getattr(ps, "_data", None) or DataPolicy()

    def _redact_event(self, ev: RunEvent) -> RunEvent:
        safe = ev.model_copy(deep=True)
        self._data_policy().sanitize_event(safe)
        return safe

    async def _emit(
        self,
        factory: Any,
        ev: RunEvent,
        *,
        terminal: bool = False,
    ) -> RunEvent:
        """脱敏后落库（及可选终态）并返回供 yield 的事件。"""
        safe = self._redact_event(ev)
        await persist_event(factory, safe)
        if terminal or safe.type in _TERMINAL:
            await _persist_terminal(factory, safe.run_id, safe)
        return safe

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
        - apply_before（Auth/Budget/Timeout）在 RUN_STARTED 之后、Executor 之前；
          策略拒绝 → HarnessError → run.failed（不进入 Executor）。
        - 落库与 SSE 下发前经 DataPolicy 脱敏（H6-4）。
        """

        run_id = run_id or str(uuid.uuid4())
        options = request.options or {}
        token = options.get("cancellation_token") or CancellationToken()
        factory = options.get("session_factory")

        ctx = RunContext(
            run_id=run_id,
            request=request,
            cancellation_token=token,
        )

        await persist_run_start(
            factory,
            run_id=run_id,
            input=request.input,
            agent_id=request.agent_id,
            session_id=request.session_id,
            status="running",
        )

        seq = 0
        started = await self._emit(
            factory,
            RunEvent(type=RUN_STARTED, run_id=run_id, sequence=seq),
        )
        yield started
        seq += 1

        saw_terminal = False
        try:
            ctx = self._apply_pre_policies(ctx)
            async for ev in self.executor.astream(ctx):
                if token.is_cancelled():
                    failed = await self._emit(
                        factory,
                        RunEvent(
                            type=RUN_FAILED,
                            run_id=run_id,
                            sequence=seq,
                            payload=_cancelled_payload(),
                        ),
                        terminal=True,
                    )
                    yield failed
                    return

                out = ev.model_copy(update={"run_id": run_id, "sequence": seq})
                safe = await self._emit(factory, out)
                if safe.type in _TERMINAL:
                    saw_terminal = True
                yield safe
                seq += 1
        except Exception as e:
            if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
                err = HarnessError.from_exception(
                    e, category=HarnessErrorCategory.TIMEOUT
                )
            elif isinstance(e, HarnessError):
                err = e
            else:
                err = HarnessError.from_exception(e)
            failed = await self._emit(
                factory,
                RunEvent(
                    type=RUN_FAILED,
                    run_id=run_id,
                    sequence=seq,
                    payload=err.to_dict(),
                ),
                terminal=True,
            )
            yield failed
            return

        if token.is_cancelled():
            failed = await self._emit(
                factory,
                RunEvent(
                    type=RUN_FAILED,
                    run_id=run_id,
                    sequence=seq,
                    payload=_cancelled_payload(),
                ),
                terminal=True,
            )
            yield failed
            return

        if not saw_terminal:
            completed = await self._emit(
                factory,
                RunEvent(
                    type=RUN_COMPLETED,
                    run_id=run_id,
                    sequence=seq,
                    payload={},
                ),
                terminal=True,
            )
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
