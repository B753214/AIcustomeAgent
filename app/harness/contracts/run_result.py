from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# succeeded / failed / cancelled；超时用 status=failed + error.type=timeout（见 HarnessError）
RunStatus = Literal["succeeded", "failed", "cancelled"]


class RunResult(BaseModel):
    """一次 Agent Run 的最终结果。

    与现有 ChatResponse 大致映射：
    - output ≈ reply
    - sources ≈ sources（此处用 list[dict]，API 层可再压成 str 列表）
    - metadata 可放 intent / engine / cache_hit 等
    - error 失败时的结构化信息（type / message / details）
    """

    status: RunStatus = Field(
        ...,
        description="终态：succeeded / failed / cancelled",
    )
    output: str | None = Field(
        default=None,
        description="对用户的主回复文本（≈ reply）",
    )
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="RAG 引用来源，如 {title, uri, snippet}",
    )
    artifacts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="较大产物引用，如告警报告路径、抓取摘要 id",
    )
    usage: dict[str, Any] = Field(
        default_factory=dict,
        description="用量：tokens / tool_calls / latency_ms 等",
    )
    error: dict[str, Any] | None = Field(
        default=None,
        description="失败时结构化错误，如 {type, message, details}",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展：intent / engine / cache_hit 等",
    )
