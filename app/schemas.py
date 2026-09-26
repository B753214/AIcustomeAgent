from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class ChatRequest(BaseModel):
    """聊天入参：非法 session_id / 空消息 / 超长 → ValidationError（HTTP 422）。"""

    message: str = Field(
        ...,
        min_length=1,
        max_length=settings.chat_message_max_chars,
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=settings.max_session_id_length,
        description="可缺省由服务端发号；禁止字面量 default",
    )

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("message")
    @classmethod
    def message_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("message is required")
        return v

    @field_validator("session_id", mode="before")
    @classmethod
    def normalize_session_id(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        s = v.strip()
        return s if s else None

    @field_validator("session_id")
    @classmethod
    def reject_default_session(cls, v: str | None) -> str | None:
        if v is not None and v.lower() == "default":
            raise ValueError("session_id must not be 'default'")
        return v


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    sources: list = []
    engine: str = "langchain"   # langchain | crew | alarm
    used_crew: bool = False
    cache_hit: bool = False
    meta: dict = {}


class IngestResponse(BaseModel):
    file_name: str
    chunks: int
    total_chunks: int


class StatsResponse(BaseModel):
    total_chunks: int
    llm_model: str
    embedding_model: str
    use_crew: bool
    crew_available: bool
    hybrid_enabled: bool = True
    bm25_ready: bool = False
    rerank_enabled: bool = False
    cache_enabled: bool = False
    cache_size: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_threshold: float = 0.0
    ratelimit_enabled: bool = False
    ratelimit_per_minute: int = 0
    ratelimit_blocked: int = 0
