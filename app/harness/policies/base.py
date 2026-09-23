from __future__ import annotations

from typing import Any

from app.harness.contracts import RunContext


class PolicySet:
    """策略组合空壳；H6 再往 before/after 里挂真实限流、预算等。"""

    def apply_before(self, ctx: RunContext) -> RunContext:
        """Executor 运行前；H3 原样返回。"""
        return ctx

    def apply_after(self, ctx: RunContext, result: Any) -> None:
        """Run 结束后；H3 空实现。result 一般为 RunResult。"""
        return None
