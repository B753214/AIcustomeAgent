from __future__ import annotations

from typing import Any

from app.harness.contracts import HarnessError, HarnessErrorCategory, RunContext


class ToolPolicy:
    """工具白名单 + 极简参数长度门禁。

    - ``allowlist=None``：不限制工具名
    - ``allowlist=set()``：全部拒绝
    """

    def __init__(
        self,
        allowlist: list[str] | set[str] | None = None,
        *,
        max_arg_chars: int = 500,
    ) -> None:
        self.allowlist: set[str] | None = (
            None if allowlist is None else set(allowlist)
        )
        self.max_arg_chars = max_arg_chars

    def check_call(
        self,
        name: str,
        args: dict[str, Any] | None,
        ctx: RunContext,
    ) -> None:
        """工具调用前检查；不通过则 raise HarnessError(POLICY)。"""
        args = args or {}
        if self.allowlist is not None:
            if not self.allowlist or name not in self.allowlist:
                raise HarnessError(
                    HarnessErrorCategory.POLICY,
                    f"工具 {name!r} 不在允许列表",
                    details={
                        "policy": "tool",
                        "tool": name,
                        "allowed": sorted(self.allowlist),
                        "agent_id": ctx.request.agent_id,
                        "caller": ctx.request.caller,
                    },
                )

        for key, value in args.items():
            if isinstance(value, str) and len(value) > self.max_arg_chars:
                raise HarnessError(
                    HarnessErrorCategory.POLICY,
                    f"工具参数 {key!r} 超长",
                    details={
                        "policy": "tool",
                        "tool": name,
                        "arg": key,
                        "length": len(value),
                        "max_arg_chars": self.max_arg_chars,
                        "agent_id": ctx.request.agent_id,
                        "caller": ctx.request.caller,
                    },
                )
