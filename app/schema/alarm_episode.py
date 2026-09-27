"""Alarm 会话情景名片 Schema（M6-A）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlarmEpisode(BaseModel):
    """写入 chat_sessions.last_alarm_episode 的结构。"""

    model_config = ConfigDict(extra="ignore")

    config_id: str | None = Field(default=None, description="【配置ID】")
    monitor_url: str | None = Field(default=None, description="监控面板 URL")
    metric: str | None = Field(default=None, description="指标名")
    indicator: str | None = Field(default=None, description="metric 别名")
    level: str | None = Field(default=None, description="如 P1/P2")
    page: int | None = Field(default=None, description="页码 / page_count")
    evidence_summary: str | None = Field(default=None, description="证据摘要（截断）")
    playbook_hint: str | None = Field(default=None, description="skill_key 等提示")
    source_run_id: str | None = Field(default=None, description="可选 harness run_id")
    updated_at: datetime | None = Field(default=None)

    @field_validator("page", mode="before")
    @classmethod
    def coerce_page(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
