from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 标准事件名（SSE / Dashboard / Trace 共用词表）
RUN_STARTED = "run.started"
ROUTE_SELECTED = "route.selected"
MODEL_STARTED = "model.started"
MODEL_TOKEN = "model.token"
MODEL_COMPLETED = "model.completed"
TOOL_STARTED = "tool.started"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"
WORKFLOW_STEP = "workflow.step"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"

EVENT_TYPES: tuple[str, ...] = (
    RUN_STARTED,
    ROUTE_SELECTED,
    MODEL_STARTED,
    MODEL_TOKEN,
    MODEL_COMPLETED,
    TOOL_STARTED,
    TOOL_COMPLETED,
    TOOL_FAILED,
    WORKFLOW_STEP,
    RUN_COMPLETED,
    RUN_FAILED,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunEvent(BaseModel):
    """通用 Agent 运行事件，用于流式输出 / 日志 / 埋点。

    约定 type 使用 EVENT_TYPES 中的常量，例如：
    run.started、route.selected、model.token、tool.started、
    workflow.step、run.completed、run.failed。
    """

    model_config = ConfigDict(
        extra="allow",
        ser_json_bytes="utf8",
        use_enum_values=True,
    )

    type: str = Field(
        ...,
        description="事件名，优先使用 EVENT_TYPES 常量（如 run.started / tool.completed）",
        min_length=1,
    )
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="事件发生时间（UTC，带时区）",
    )
    run_id: str = Field(
        ...,
        description="所属运行的唯一 ID",
        min_length=1,
    )
    sequence: int = Field(
        ...,
        ge=0,
        description="同一 run 内的递增序号，从 0 起",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="事件载荷，如 {'content': '...'} / {'tool': 'query_order'}",
    )
    visibility: Literal["public", "internal"] = Field(
        default="public",
        description="public 可透传给前端；internal 仅供内部日志/调试",
    )
