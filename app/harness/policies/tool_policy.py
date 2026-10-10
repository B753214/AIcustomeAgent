from __future__ import annotations

from typing import Any, Iterable

from app.harness.contracts import HarnessError, HarnessErrorCategory, RunContext


def is_tool_allowed(name: str, allowlist: Iterable[str] | None) -> bool:
    """白名单是否允许该工具名。

    - ``None``：不限制
    - 精确匹配，或 ``prefix*`` 前缀匹配（``*`` 前至少一字，如 ``maps_*``）
    - 空列表：全部拒绝
    """
    if allowlist is None:
        return True
    patterns = list(allowlist)
    if not patterns:
        return False
    if name in patterns:
        return True
    for pattern in patterns:
        if len(pattern) > 1 and pattern.endswith("*") and name.startswith(pattern[:-1]):
            return True
    return False


class ToolPolicy:
    """工具白名单（不检查参数长度）。

    - ``allowlist=None``：不限制工具名
    - ``allowlist=[]`` / 空 set：全部拒绝
    - 条目可为精确名或 ``prefix*``（如 ``maps_*``）
    """

    def __init__(
        self,
        allowlist: list[str] | set[str] | None = None,
    ) -> None:
        self.allowlist: set[str] | None = (
            None if allowlist is None else set(allowlist)
        )

    def check_call(
        self,
        name: str,
        args: dict[str, Any] | None,
        ctx: RunContext,
    ) -> None:
        """工具调用前检查；不通过则 raise HarnessError(POLICY)。"""
        if not is_tool_allowed(name, self.allowlist):
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"工具 {name!r} 不在允许列表",
                details={
                    "policy": "tool",
                    "tool": name,
                    "allowed": sorted(self.allowlist or ()),
                    "agent_id": ctx.request.agent_id,
                    "caller": ctx.request.caller,
                },
            )
