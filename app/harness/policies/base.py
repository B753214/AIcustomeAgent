from __future__ import annotations

from typing import Any

from app.harness.contracts import RunContext

from .auth import AuthPolicy
from .budget import BudgetPolicy
from .cache import CachePolicy
from .data import DataPolicy
from .retry import RetryPolicy
from .timeout import TimeoutPolicy
from .tool_policy import ToolPolicy


class PolicySet:
    """策略组合：Run 前串 Auth → Budget → Timeout（其余策略先挂属性，后续接线）。"""

    def __init__(
        self,
        *,
        auth: AuthPolicy | None = None,
        budget: BudgetPolicy | None = None,
        timeout: TimeoutPolicy | None = None,
        data: DataPolicy | None = None,
        cache: CachePolicy | None = None,
        retry: RetryPolicy | None = None,
        tool: ToolPolicy | None = None,
    ) -> None:
        self._auth = auth
        self._budget = budget
        self._timeout = timeout
        self._data = data
        self._cache = cache
        self._retry = retry
        self._tool = tool

    def apply_before(self, ctx: RunContext) -> RunContext:
        """Executor 运行前：鉴权 → 预算初始化/检查 → 写入 deadline。"""
        if self._auth:
            self._auth.check(ctx)
        if self._budget:
            ctx = self._budget.ensure_budget(ctx)
            self._budget.check(ctx)
        if self._timeout:
            ctx = self._timeout.apply_deadline(ctx)
        return ctx

    def apply_after(self, ctx: RunContext, result: Any) -> None:
        """Run 结束后钩子（审计/缓存等）；H6-2 先空实现。"""
        return None
