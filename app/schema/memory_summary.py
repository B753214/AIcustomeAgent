"""会话滚动摘要 JSON Schema（M3-3）；生成/落库见 M3-4～M3-6。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionSummaryPayload(BaseModel):
    """结构化摘要：主题 + 事实 / 决策 / 未决问题。"""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1, description="会话主题一句话")
    known_facts: list[str] = Field(default_factory=list, description="已确认事实")
    decisions: list[str] = Field(default_factory=list, description="已做决策")
    unresolved: list[str] = Field(default_factory=list, description="未解决问题")

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("known_facts", "decisions", "unresolved", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v: object) -> object:
        if v is None:
            return []
        return v
