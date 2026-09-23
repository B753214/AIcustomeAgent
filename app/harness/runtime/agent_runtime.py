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

_TERMINAL = frozenset({RUN_COMPLETED, RUN_FAILED})


def _cancelled_payload() -> dict[str, Any]:
    return {
        "category": "policy",
        "message": "run cancelled",
        "details": {},
        "cancelled": True,
    }


class AgentRuntime:
    """统一开跑门面：建 Run、转发 Executor 事件、归一失败。"""

    def __init__(
        self,
        executor: AgentExecutor,
        *,
        policy_registry: PolicyRegistry | None = None,
        policy_set: str = "default",
    ) -> None:
        # executor 仍可直接注入；H4 再换成从 AgentRegistry 按 agent_id 取
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

    async def execute_stream(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """把一次 RunRequest 变成有序 RunEvent 流。

        SSE / DB 事务约定（H2-5）：
        - Runtime 与 Executor 默认不持有 SQLAlchemy AsyncSession。
        - 禁止用「同一个 session」包住整段 async for 事件推流。
        - 禁止用「同一个 session」包住整段 async for 事件推流。
        - 若需读写会话/Run：在 Adapter 或仓储层短开短关（打开→读写→关闭），
          再继续推流；完整 SSE 改造（拆 Depends(get_db)、接 Runtime）延期到
          ChatExecutor（H4）之后单独做，本阶段仅固化约定。
        """
        run_id = str(uuid.uuid4())
        token = CancellationToken()
        ctx = self._apply_pre_policies(
            RunContext(
                run_id=run_id,
                request=request,
                cancellation_token=token,
            )
        )

        seq = 0
        yield RunEvent(type=RUN_STARTED, run_id=run_id, sequence=seq)
        seq += 1

        saw_terminal = False
        try:
            async for ev in self.executor.astream(ctx):
                if token.is_cancelled():
                    yield RunEvent(
                        type=RUN_FAILED,
                        run_id=run_id,
                        sequence=seq,
                        payload=_cancelled_payload(),
                    )
                    return

                out = ev.model_copy(update={"run_id": run_id, "sequence": seq})
                if out.type in _TERMINAL:
                    saw_terminal = True
                yield out
                seq += 1
        except Exception as e:
            err = HarnessError.from_exception(e)
            yield RunEvent(
                type=RUN_FAILED,
                run_id=run_id,
                sequence=seq,
                payload=err.to_dict(),
            )
            return

        if token.is_cancelled():
            yield RunEvent(
                type=RUN_FAILED,
                run_id=run_id,
                sequence=seq,
                payload=_cancelled_payload(),
            )
            return

        if not saw_terminal:
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=run_id,
                sequence=seq,
                payload={},
            )

    async def execute(self, request: RunRequest) -> RunResult:
        """消费 execute_stream，聚合成一次 RunResult（无第二套业务路径）。"""
        status: str | None = None
        output: str | None = None
        error: dict[str, Any] | None = None
        sources: list[Any] = []
        usage: dict[str, Any] = {}
        metadata: dict[str, Any] = {}
        output_parts: list[str] = []

        async for ev in self.execute_stream(request):
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
                # 取消：status=cancelled；其它失败：failed
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

        return RunResult(
            status=status,  # type: ignore[arg-type]
            output=output,
            error=error,
            sources=sources,
            usage=usage,
            metadata=metadata,
        )
