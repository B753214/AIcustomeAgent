import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import Mapped, relationship, mapped_column

from app.database import Base


class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    session_id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(), comment="会话创建时间"
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="会话结束时间"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ChatSession(session_id={self.session_id})>"

class ChatMessage(Base):
    """消息表：存储每条对话消息"""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        index=True, comment="关联业务会话ID"
    )
    role: Mapped[str] = mapped_column(
        String(20), comment="消息角色：user/assistant/system"
    )
    content: Mapped[str] = mapped_column(
        Text, comment="消息内容"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(), comment="消息创建时间"
    )

    # 反向关联会话表
    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    # 复合索引：按会话+时间排序查询
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage(session={self.session_id}, role={self.role})>"
