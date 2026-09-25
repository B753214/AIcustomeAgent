from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.harness.contracts import RunContext


class TimeoutPolicy:
    """分层超时：Run / model / tool 秒数；写入 ctx.deadline 与 metadata。"""

    def __init__(
        self,
        run_seconds: float = 120,
        model_seconds: float = 60,
        tool_seconds: float = 30,
    ) -> None:
        self.run_seconds = run_seconds
        self.model_seconds = model_seconds
        self.tool_seconds = tool_seconds

    def apply_deadline(self, ctx: RunContext) -> RunContext:
        """若尚无 deadline，用 now + run_seconds 写入；并记录分层超时配置。"""
        if ctx.deadline is not None:
            return ctx
        ctx.deadline = datetime.now(timezone.utc) + timedelta(
            seconds=self.run_seconds
        )
        ctx.metadata.setdefault(
            "timeout",
            {
                "run_seconds": self.run_seconds,
                "model_seconds": self.model_seconds,
                "tool_seconds": self.tool_seconds,
            },
        )
        return ctx
