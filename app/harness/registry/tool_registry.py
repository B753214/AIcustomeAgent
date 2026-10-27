from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from app.harness.contracts import ToolSpec

ToolHandler = Callable[..., Any]
ToolEntry = tuple[ToolSpec, ToolHandler]


class ToolRegistry:
    """工具花名册：name → (ToolSpec, handler)。只登记，不执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}
        self._model_tools: dict[str, Any] = {}

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

    def has_model_tool(self, tool: Any) -> bool:
        return self._model_tools.get(tool.name) is tool

    def register_model_tool(self, tool: Any, *, timeout_sec: float = 30.0) -> None:
        """将适配后的 MCP/其他 LangChain 工具登记为 Spec 和异步 handler。"""
        schema = tool.args_schema
        if not isinstance(schema, dict):
            schema = tool.get_input_schema().model_json_schema()

        async def handler(**arguments: Any) -> Any:
            return await tool.ainvoke(arguments)

        self.register(
            ToolSpec(name=tool.name, description=tool.description or tool.name,
                     input_schema=schema, timeout_sec=timeout_sec),
            handler,
        )
        self._model_tools[tool.name] = tool

    def list_model_tools(self, allowlist: list[str] | None = None) -> list[Any]:
        """本地和 MCP 共用模型工具来源；绑定时应用同一白名单。"""
        from langchain_core.tools import StructuredTool
        from app.harness.policies.tool_policy import is_tool_allowed

        result = []
        for name, (spec, handler) in self._tools.items():
            if not is_tool_allowed(name, allowlist):
                continue
            if name not in self._model_tools:
                kwargs = ({"coroutine": handler} if inspect.iscoroutinefunction(handler)
                          else {"func": handler})
                self._model_tools[name] = StructuredTool.from_function(
                    name=name, description=spec.description,
                    args_schema=spec.input_schema, **kwargs,
                )
            result.append(self._model_tools[name])
        return result


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


_builtin_tool_registry: ToolRegistry | None = None


def get_builtin_tool_registry() -> ToolRegistry:
    """进程内单例：内置工具只注册一次。"""
    global _builtin_tool_registry
    if _builtin_tool_registry is None:
        _builtin_tool_registry = register_builtin_tools(ToolRegistry())
    return _builtin_tool_registry
