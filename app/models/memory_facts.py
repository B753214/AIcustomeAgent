"""长期事实表：跨会话 Semantic Memory（M4）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, ForeignKey, Text, DateTime, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MemoryFact(Base):
    """长期事实记忆：profile / preference / constraint / business_fact。"""

    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(128),
        default="anonymous",
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="profile / preference / constraint / business_fact",
    )
    normalized_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="去重冲突键，如 response_style",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="规范化事实文本")
    confidence: Mapped[float] = mapped_column(
        default=1.0, nullable=False, comment="抽取置信度 0.0-1.0"
    )
    importance: Mapped[int] = mapped_column(
        default=0, nullable=False, comment="召回优先级，数字越大越优先"
    )
    source_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="事实来源消息",
    )
    source_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="explicit",
        comment="explicit / inferred / imported",
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="candidate",
        index=True,
        comment="candidate / active / superseded / deleted",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow_naive
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow_naive, onupdate=_utcnow_naive
    )

    __table_args__ = (
        # 非唯一：允许 superseded 与新行共存；当前有效行由 partial unique 约束（见 init_db ensure）
        Index(
            "ix_memory_facts_user_kind_key",
            "tenant_id",
            "user_id",
            "kind",
            "normalized_key",
        ),
        Index(
            "ix_memory_facts_status_user",
            "status",
            "tenant_id",
            "user_id",
        ),
        Index(
            "uq_memory_facts_live_key",
            "tenant_id",
            "user_id",
            "kind",
            "normalized_key",
            unique=True,
            postgresql_where=text("status IN ('active', 'candidate')"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryFact(id={self.id}, kind={self.kind}, key={self.normalized_key})>"
        )
