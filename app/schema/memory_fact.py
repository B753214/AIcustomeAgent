"""长期事实 Schema：抽取候选（M4-2）+ API DTO（M4-6）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FactKind = Literal["profile", "preference", "constraint", "business_fact"]
SourceType = Literal["explicit", "inferred", "imported"]
FactStatus = Literal["candidate", "active", "superseded", "deleted"]


class MemoryFactCandidate(BaseModel):
    """单条抽取候选，字段对齐 memory_facts / should_persist_fact。"""

    model_config = ConfigDict(extra="forbid")

    kind: FactKind = Field(..., description="profile/preference/constraint/business_fact")
    normalized_key: str = Field(..., min_length=1, description="去重键，如 display_name")
    content: str = Field(..., min_length=1, description="规范化事实文本")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="0~1 置信度")
    source_type: SourceType = Field("inferred", description="explicit/inferred/imported")
    sensitive: bool = Field(False, description="敏感则不得直接 active")

    @field_validator("normalized_key", "content", mode="before")
    @classmethod
    def strip_str(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class MemoryFactExtractResult(BaseModel):
    """LLM 结构化抽取结果。"""

    model_config = ConfigDict(extra="forbid")

    facts: list[MemoryFactCandidate] = Field(default_factory=list)


class MemoryFactOut(BaseModel):
    """API 响应：对外用 key，对应库字段 normalized_key。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    key: str
    content: str
    status: str
    confidence: float
    source_type: str
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: object) -> MemoryFactOut:
        return cls(
            id=str(getattr(row, "id")),
            kind=str(getattr(row, "kind")),
            key=str(getattr(row, "normalized_key")),
            content=str(getattr(row, "content")),
            status=str(getattr(row, "status")),
            confidence=float(getattr(row, "confidence") or 0.0),
            source_type=str(getattr(row, "source_type")),
            updated_at=getattr(row, "updated_at", None),
        )


class MemoryFactUpdate(BaseModel):
    """PATCH body：仅允许改 content。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v
