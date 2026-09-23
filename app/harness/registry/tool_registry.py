from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.harness.contracts import ToolSpec

ToolHandler = Callable[..., Any]
ToolEntry = tuple[ToolSpec, ToolHandler]


class ToolRegistry:
    """工具花名册：name → (ToolSpec, handler)。只登记，不执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = (spec, handler)

    def get(self, name: str) -> ToolEntry:
        if name not in self._tools:
            raise ValueError(f"tool {name!r} not registered")
        return self._tools[name]

    def get_spec(self, name: str) -> ToolSpec:
        return self.get(name)[0]

    def list_specs(self, allowlist: list[str] | None = None) -> list[ToolSpec]:
        """列出说明书；allowlist 为「已注册 ∩ 白名单」（未知名静默跳过）。"""
        if allowlist is None:
            return [spec for spec, _ in self._tools.values()]
        return [self._tools[n][0] for n in allowlist if n in self._tools]

    # 与计划别名兼容
    get_specs = list_specs

    def list_names(self) -> list[str]:
        return list(self._tools.keys())


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """登记现有订单/天气工具（handler 用原函数，不在此执行）。"""
    from app.agents.tools import query_order
    from app.agents.weather import query_weather
    from app.config import settings

    timeout = float(getattr(settings, "tool_timeout_sec", 30.0) or 30.0)

    registry.register(
        ToolSpec(
            name="query_order",
            description="查询订单状态与物流（Mock）",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            timeout_sec=timeout,
            idempotent=True,
        ),
        query_order,
    )
    registry.register(
        ToolSpec(
            name="query_weather",
            description="获取指定位置的实时天气",
            input_schema={
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
            timeout_sec=timeout,
            idempotent=True,
        ),
        query_weather,
    )
    return registry
