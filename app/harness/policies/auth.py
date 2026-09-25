from __future__ import annotations

from app.harness.contracts import HarnessError, HarnessErrorCategory, RunContext


class AuthPolicy:
    """校验 caller 是否有权运行当前 Agent / 工具。

    - ``allowlist`` 为 None 表示不限制（放行所有 caller）。
    - ``allowlist`` 为空集合表示全部拒绝。
    - 命中规则时静默返回；不命中时 raise HarnessError(category=POLICY)。

    用法（组合进 PolicySet）::

        class MyPolicySet(PolicySet):
            def __init__(self):
                self._auth = AuthPolicy(allowlist={"api", "internal"})

            def apply_before(self, ctx):
                self._auth.check(ctx)
                return ctx
    """

    def __init__(self, allowlist: set[str] | list[str] | None = None) -> None:
        self.allowlist: set[str] | None = (
            None if allowlist is None else set(allowlist)
        )

    def check(self, ctx: RunContext) -> None:
        caller = ctx.request.caller

        if self.allowlist is None:
            return

        if not self.allowlist:
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"caller {caller!r} 无权运行 (allowlist 为空)",
                details={
                    "policy": "auth",
                    "caller": caller,
                    "agent_id": ctx.request.agent_id,
                },
            )

        if caller not in self.allowlist:
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"caller {caller!r} 无权运行 agent {ctx.request.agent_id!r}",
                details={
                    "policy": "auth",
                    "caller": caller,
                    "allowed": sorted(self.allowlist),
                    "agent_id": ctx.request.agent_id,
                },
            )