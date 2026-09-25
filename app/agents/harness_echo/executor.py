"""Harness EchoExecutor：玩具 Agent，证明只注册即可扩展。"""
from __future__ import annotations

from typing import AsyncIterator

from app.harness.contracts import RUN_COMPLETED, RunContext, RunEvent


class EchoExecutor:
    """把 request.input 原样放进 run.completed.output。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type=RUN_COMPLETED,
            run_id=ctx.run_id,
            sequence=0,
            payload={"output": ctx.request.input},
        )
