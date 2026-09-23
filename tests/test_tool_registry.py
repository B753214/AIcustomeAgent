"""H3-3：ToolRegistry 注册 / 获取 / 白名单过滤。"""
from __future__ import annotations

import pytest

from app.agents.tools import query_order
from app.agents.weather import query_weather
from app.harness.contracts import ToolSpec
from app.harness.registry.tool_registry import ToolRegistry, register_builtin_tools


def test_register_get_and_list_specs():
    registry = ToolRegistry()
    spec = ToolSpec(name="test", description="test tool")
    handler = lambda x: x  # noqa: E731
    registry.register(spec, handler)

    got_spec, got_handler = registry.get("test")
    assert got_spec is spec
    assert got_handler is handler
    assert registry.get_spec("test") is spec
    assert registry.list_specs() == [spec]
    assert registry.list_specs(["test"]) == [spec]
    # 别名
    assert registry.get_specs(["test"]) == [spec]


def test_list_specs_allowlist_intersection():
    registry = ToolRegistry()
    registry.register(ToolSpec(name="a", description="a"), lambda: None)
    registry.register(ToolSpec(name="b", description="b"), lambda: None)

    specs = registry.list_specs(["b", "missing", "a"])
    assert [s.name for s in specs] == ["b", "a"]


def test_get_unknown_raises():
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="not registered"):
        registry.get("nope")


def test_register_duplicate_raises():
    registry = ToolRegistry()
    spec = ToolSpec(name="x", description="x")
    registry.register(spec, lambda: None)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec, lambda: None)


def test_register_builtin_order_and_weather():
    registry = register_builtin_tools(ToolRegistry())
    assert set(registry.list_names()) == {"query_order", "query_weather"}

    order_spec, order_handler = registry.get("query_order")
    assert order_spec.idempotent is True
    assert "message" in order_spec.input_schema.get("properties", {})
    assert order_handler is query_order

    weather_spec, weather_handler = registry.get("query_weather")
    assert "location" in weather_spec.input_schema.get("properties", {})
    assert weather_handler is query_weather

    only_order = registry.list_specs(["query_order"])
    assert [s.name for s in only_order] == ["query_order"]
