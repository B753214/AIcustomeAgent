from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .run_request import RunRequest


class RunContext(BaseModel):
    """通用 Agent 运行上下文（执行态；不进入 Registry）。"""

    run_id: str = Field(
        ...,
        description="本次运行唯一 ID（UUID 字符串即可）",
    )
    trace_id: str | None = Field(
        default=None,
        description="请求跟踪 ID，用于日志关联",
    )
    request: RunRequest = Field(
        ...,
        description="原始请求",
    )
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="会话消息列表",
    )
    permissions: dict[str, Any] = Field(
        default_factory=dict,
        description="权限信息",
    )
    deadline: datetime | None = Field(
        default=None,
        description="截止时间，None 表示无超时",
    )
    budget: dict[str, Any] = Field(
        default_factory=dict,
        description="预算，如 max_tool_calls / max_tokens",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="其它元数据",
    )
