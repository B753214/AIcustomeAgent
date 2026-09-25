from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class HarnessRun(Base):
    """Harness 一次 Agent 运行的台账（非聊天消息）。"""

    __tablename__ = "harness_runs"

    run_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="运行 ID（与 Runtime run_id 对齐）",
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Agent 标识：chat / knowledge / alarm",
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="会话 ID",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="running",
        comment="running / succeeded / failed / cancelled",
    )
    input: Mapped[str] = mapped_column(Text, comment="运行输入")
    output: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="运行输出摘要",
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="结构化错误",
    )
    usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="用量：tokens 等",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow_naive,
        comment="开始时间",
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="结束时间",
    )

    __table_args__ = (
        Index("ix_harness_runs_session_status", "session_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<HarnessRun(run_id={self.run_id}, status={self.status})>"


class HarnessCheckpoint(Base):
    """Run 进度检查点：同一 run_id 下按 name 覆盖更新。"""

    __tablename__ = "harness_checkpoints"

    run_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="关联 harness_runs.run_id",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        comment="检查点名，如 alarm.after_fetch",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="检查点内容",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
        comment="更新时间",
    )

    __table_args__ = (
        Index("ix_harness_checkpoints_run", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<HarnessCheckpoint(run_id={self.run_id}, name={self.name})>"


class HarnessRunEvent(Base):
    """Run 事件流：可按 run_id + sequence 回放。"""

    __tablename__ = "harness_run_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="事件行 ID",
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        comment="关联 harness_runs.run_id",
    )
    sequence: Mapped[int] = mapped_column(
        comment="同一 run 内的递增序号（从 0 起）",
    )
    type: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment="事件名：run.started / model.token / tool.completed ...",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="事件载荷（入库前可裁剪大字段）",
    )
    visibility: Mapped[str] = mapped_column(
        String(16),
        default="public",
        comment="public 可透传前端；internal 通常不入库",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow_naive,
        comment="事件发生时间",
    )

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_harness_run_events_run_seq"),
        Index("ix_harness_run_events_run_time", "run_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<HarnessRunEvent(id={self.id}, run_id={self.run_id}, "
            f"seq={self.sequence}, type={self.type})>"
        )
