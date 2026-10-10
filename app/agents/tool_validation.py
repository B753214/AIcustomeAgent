"""工具参数校验：类型 + 完整性（必填）；不做超长限制。"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

TOOL_ERROR_PREFIX = "[TOOL_ERROR]"

_LOCATION_RE = re.compile(r"^[\w\u4e00-\u9fff\s,.\-／/]+$", re.UNICODE)


class QueryOrderArgs(BaseModel):
    """query_order 入参。"""

    message: str = Field(..., min_length=1, description="用户原话或订单号")

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
        description="城市拼音/中文名/经纬度，如 beijing、杭州、116.40,39.90",
    )

    @field_validator("location", mode="before")
    @classmethod
    def _normalize_location(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("location 不能为空")
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
    """无 Schema 时做类型向清洗：保留常见标量/列表，其它转 str；不截断。"""
    cleaned: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, str):
            cleaned[key] = value.strip()
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, str):
                    items.append(item.strip())
                elif isinstance(item, (int, float, bool)) or item is None:
                    items.append(item)
                else:
                    items.append(str(item))
            cleaned[key] = items
        else:
            cleaned[key] = str(value)
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
    """校验并规范化工具参数（类型 / 必填）；不做超长检查。

    Returns:
        (cleaned_args, None) 成功；
        (None, error_message) 失败（已带 TOOL_ERROR_PREFIX）。
    """
    if args is not None and not isinstance(args, dict):
        return None, f"{TOOL_ERROR_PREFIX} 工具 {name} 参数无效：args 必须是对象"
    raw = dict(args or {})

    schema = _schema_of(tool, name)
    if schema is None:
        return _sanitize_loose_args(raw), None

    try:
        model = schema.model_validate(raw)
        if hasattr(model, "model_dump"):
            return model.model_dump(), None
        return model.dict(), None  # type: ignore[attr-defined]
    except ValidationError as exc:
        return None, _format_validation_error(name, exc)
    except Exception as exc:
        return None, f"{TOOL_ERROR_PREFIX} 工具 {name} 参数无效：{exc}"
