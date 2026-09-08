"""工具参数校验：本地工具显式 Schema + MCP 工具走 args_schema。"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

TOOL_ERROR_PREFIX = "[TOOL_ERROR]"

# 单字段字符串上限，防止模型塞超长垃圾参数
MAX_ARG_CHARS = 500
MAX_LOCATION_CHARS = 100

_LOCATION_RE = re.compile(r"^[\w\u4e00-\u9fff\s,.\-／/]+$", re.UNICODE)


class QueryOrderArgs(BaseModel):
    """query_order 入参。"""

    message: str = Field(..., min_length=1, max_length=MAX_ARG_CHARS, description="用户原话或订单号")

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_message(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("message 不能为空")
        return text


class QueryWeatherArgs(BaseModel):
    """query_weather 入参。"""

    location: str = Field(
        ...,
        min_length=1,
        max_length=MAX_LOCATION_CHARS,
        description="城市拼音/中文名/经纬度，如 beijing、杭州、116.40,39.90",
    )

    @field_validator("location", mode="before")
    @classmethod
    def _normalize_location(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("location 不能为空")
        if len(text) > MAX_LOCATION_CHARS:
            raise ValueError(f"location 过长（>{MAX_LOCATION_CHARS}）")
        if not _LOCATION_RE.match(text):
            raise ValueError("location 含非法字符，仅支持中英文、数字、逗号、点、短横线")
        return text


_LOCAL_SCHEMAS: dict[str, type[BaseModel]] = {
    "query_order": QueryOrderArgs,
    "query_weather": QueryWeatherArgs,
}


def _format_validation_error(name: str, exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err.get("loc") or ()) or "args"
        msg = err.get("msg") or "无效"
        parts.append(f"{loc}: {msg}")
    detail = "；".join(parts) if parts else str(exc)
    return f"{TOOL_ERROR_PREFIX} 工具 {name} 参数无效：{detail}"


def _sanitize_loose_args(args: dict[str, Any]) -> dict[str, Any]:
    """无 Schema 时做保守清洗：只要 dict、字符串截断。"""
    cleaned: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, str):
            cleaned[key] = value.strip()[:MAX_ARG_CHARS]
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, list):
            # MCP 偶发 list；限制长度与元素类型
            items = []
            for item in value[:20]:
                if isinstance(item, str):
                    items.append(item.strip()[:MAX_ARG_CHARS])
                elif isinstance(item, (int, float, bool)) or item is None:
                    items.append(item)
            cleaned[key] = items
        else:
            cleaned[key] = str(value)[:MAX_ARG_CHARS]
    return cleaned


def _schema_of(tool: Any, name: str) -> type[BaseModel] | None:
    local = _LOCAL_SCHEMAS.get(name)
    if local is not None:
        return local
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    return None


def validate_tool_args(
    tool: Any,
    name: str,
    args: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """校验并规范化工具参数。

    Returns:
        (cleaned_args, None) 成功；
        (None, error_message) 失败（已带 TOOL_ERROR_PREFIX）。
    """
    raw = dict(args or {})
    if not isinstance(raw, dict):
        return None, f"{TOOL_ERROR_PREFIX} 工具 {name} 参数无效：args 必须是对象"

    schema = _schema_of(tool, name)
    if schema is None:
        return _sanitize_loose_args(raw), None

    try:
        model = schema.model_validate(raw)
        # pydantic v2
        if hasattr(model, "model_dump"):
            return model.model_dump(), None
        return model.dict(), None  # type: ignore[attr-defined]
    except ValidationError as exc:
        return None, _format_validation_error(name, exc)
    except Exception as exc:
        return None, f"{TOOL_ERROR_PREFIX} 工具 {name} 参数无效：{exc}"
