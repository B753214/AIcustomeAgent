from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """工具静态说明书（Registry 存 Spec，ToolRunner 按 Spec 执行）。

    示例（query_order）：
        ToolSpec(
            name="query_order",
            description="查询订单状态与物流（Mock）",
            input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
            timeout_sec=30,
            idempotent=True,
        )
    """

    name: str = Field(..., description="工具唯一名，如 query_order")
    version: str = Field(default="1.0", description="Schema/行为版本，便于灰度")
    description: str = Field(..., description="给模型或文档看的说明")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema 或等价参数描述",
    )
    permissions: dict[str, Any] = Field(
        default_factory=dict,
        description="调用权限，如允许的 agent_id / caller",
    )
    timeout_sec: float = Field(
        default=30.0,
        description="单次工具超时（秒），对齐 TOOL_TIMEOUT_SEC",
        gt=0,
    )
    retry: int = Field(
        default=0,
        description="允许的额外重试次数",
        ge=0,
    )
    idempotent: bool = Field(
        default=False,
        description="重试/恢复是否安全（无副作用或可幂等）",
    )
