"""本次 Run 的工具执行绑定（ContextVar，供 chat_graph 等深处读取）。"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator

from app.harness.contracts import RunContext
from app.harness.policies.budget import BudgetPolicy
from app.harness.policies.tool_policy import ToolPolicy
from app.harness.tools.tool_runner import ToolRunner


@dataclass(frozen=True)
class ToolRunBinding:
    ctx: RunContext
    runner: ToolRunner
    policy: ToolPolicy | None = None
    allowlist: list[str] | None = None
    budget: BudgetPolicy | None = None


_binding: ContextVar[ToolRunBinding | None] = ContextVar(
    "harness_tool_run_binding",
    default=None,
)


def get_tool_run_binding() -> ToolRunBinding | None:
    return _binding.get()


@contextmanager
def tool_run_scope(
    ctx: RunContext,
    runner: ToolRunner,
    *,
    policy: ToolPolicy | None = None,
    allowlist: list[str] | None = None,
    budget: BudgetPolicy | None = None,
) -> Iterator[ToolRunBinding]:
    """在 Runtime → Executor → chat_graph 调用链上挂起工具策略绑定。"""
    binding = ToolRunBinding(
        ctx=ctx,
        runner=runner,
        policy=policy,
        allowlist=None if allowlist is None else list(allowlist),
        budget=budget,
    )
    token: Token = _binding.set(binding)
    try:
        yield binding
    finally:
        _binding.reset(token)


def merge_allowlist(
    base: list[str] | None,
    extra_names: list[str] | Any,
) -> list[str] | None:
    """显式合并两份白名单（调用方自行决定 extra）；None 表示不限制名。

    注意：chat 主路径不再用本函数自动并入全部 MCP；MCP 须写进 Agent
    ``tool_allowlist``（或 ``maps_*`` 前缀）。
    """
    if base is None:
        return None
    seen: dict[str, None] = {n: None for n in base}
    for name in extra_names or []:
        if name:
            seen[str(name)] = None
    return list(seen.keys())
