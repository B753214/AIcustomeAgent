from __future__ import annotations

from app.harness.contracts import HarnessError, HarnessErrorCategory, RunContext


class BudgetPolicy:
    """限制 Run 的工具调用次数 / token 消耗，防止无限刷模型。

    - ``max_tool_calls=None`` / ``max_tokens=None`` 表示不限制对应维度。
    - 预算上限会注入到 ``ctx.budget``（不覆盖外部预填的值）。
    - 已消耗计数同样存在 ``ctx.budget`` 中，由 ``increment`` 维护。
    - 超限时 raise ``HarnessError(category=POLICY)``，Runtime 会捕获成 RUN_FAILED。

    ``ctx.budget`` 结构约定::

        {
            "max_tool_calls": 10,       # 上限（None 或 key 不存在表示不限）
            "max_tokens": 10000,        # 上限
            "tool_calls_used": 0,       # 已消耗（由 increment 累加）
            "tokens_used": 0,           # 已消耗
        }

    用法（组合进 PolicySet）::

        class ChatPolicySet(PolicySet):
            def __init__(self):
                self._auth = AuthPolicy(allowlist={"api"})
                self._budget = BudgetPolicy(max_tool_calls=10, max_tokens=8000)

            def apply_before(self, ctx):
                self._auth.check(ctx)
                ctx = self._budget.ensure_budget(ctx)   # 初始化 ctx.budget
                self._budget.check(ctx)                  # Run 启动前也查一次
                return ctx

        # Executor 里每次工具调用前 / 模型调用后：
        # budget.check(ctx)                       # 调用前查上限
        # await tool_runner.arun(...)
        # budget.increment(ctx, tool_calls=1)     # 成功后累加
        # # 模型返回 usage 后：
        # budget.increment(ctx, tokens=usage["total_tokens"])
    """

    def __init__(
        self,
        max_tool_calls: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.max_tool_calls = max_tool_calls
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------

    def ensure_budget(self, ctx: RunContext) -> RunContext:
        """Run 启动时调用：把预算上限注入 ctx.budget，并初始化已消耗计数。

        - 不覆盖 ``ctx.budget`` 里已经预设好的上限（支持外部提前塞值）。
        - 已消耗计数初始化为 0（如果不存在的话）。
        - 返回同一个 ctx（方便 PolicySet.apply_before 链式调用）。
        """
        budget = ctx.budget
        if "max_tool_calls" not in budget and self.max_tool_calls is not None:
            budget["max_tool_calls"] = self.max_tool_calls
        if "max_tokens" not in budget and self.max_tokens is not None:
            budget["max_tokens"] = self.max_tokens
        budget.setdefault("tool_calls_used", 0)
        budget.setdefault("tokens_used", 0)
        return ctx

    # ------------------------------------------------------------------
    # 计数维护
    # ------------------------------------------------------------------

    def increment(
        self,
        ctx: RunContext,
        *,
        tool_calls: int = 0,
        tokens: int = 0,
    ) -> None:
        """累加已消耗的计数（每次 tool 成功后 / model 返回后调用）。"""
        budget = ctx.budget
        if tool_calls:
            budget["tool_calls_used"] = int(budget.get("tool_calls_used", 0)) + tool_calls
        if tokens:
            budget["tokens_used"] = int(budget.get("tokens_used", 0)) + tokens

    # ------------------------------------------------------------------
    # 上限检查
    # ------------------------------------------------------------------

    def check(self, ctx: RunContext) -> None:
        """检查是否超限；不超静默返回，超则 raise HarnessError。

        每次 tool 调用前、每次 model 调用前都应该调一次。
        """
        budget = ctx.budget
        used_tools = int(budget.get("tool_calls_used", 0))
        max_tools = budget.get("max_tool_calls")
        if max_tools is not None and used_tools >= int(max_tools):
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"tool_calls 超预算: {used_tools} >= {max_tools}",
                details={
                    "policy": "budget",
                    "dimension": "tool_calls",
                    "used": used_tools,
                    "max": int(max_tools),
                    "agent_id": ctx.request.agent_id,
                    "caller": ctx.request.caller,
                },
            )

        used_tokens = int(budget.get("tokens_used", 0))
        max_tokens = budget.get("max_tokens")
        if max_tokens is not None and used_tokens >= int(max_tokens):
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"tokens 超预算: {used_tokens} >= {max_tokens}",
                details={
                    "policy": "budget",
                    "dimension": "tokens",
                    "used": used_tokens,
                    "max": int(max_tokens),
                    "agent_id": ctx.request.agent_id,
                    "caller": ctx.request.caller,
                },
            )