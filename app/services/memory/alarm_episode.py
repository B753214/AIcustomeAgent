"""Alarm 会话情景（M6-A）：读写 last_alarm_episode、追问合并、从结果提炼。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.alarm_episode import AlarmEpisode
from app.services.session_service import get_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_alarm_episode(
    user_id: str,
    session_id: str,
    db: AsyncSession,
) -> dict | None:
    """按属主读取会话上的 Alarm 名片。"""
    row = await get_session(session_id, user_id, db)
    if row is None:
        return None
    ep = row.last_alarm_episode
    return ep if isinstance(ep, dict) else None


async def save_alarm_episode(
    user_id: str,
    session_id: str,
    episode: dict,
    db: AsyncSession,
) -> None:
    """覆盖写入 last_alarm_episode；空名片不写，避免抹掉旧数据。"""
    if not episode:
        return
    row = await get_session(session_id, user_id, db)
    if row is None:
        return
    data = AlarmEpisode.model_validate(episode).model_dump(mode="python")
    if not data.get("config_id") and not data.get("monitor_url"):
        return
    data["updated_at"] = _utcnow_naive()
    row.last_alarm_episode = data
    row.updated_at = _utcnow_naive()
    await db.flush()


def merge_alarm_followup(message: str, episode: dict | None) -> str:
    """用名片拼伪告警输入；无名片关键字段则退回原 message。"""
    ep = episode or {}
    config_id = ep.get("config_id") or ""
    url = ep.get("monitor_url") or ep.get("detail_url") or ""
    if not config_id and not url:
        return message

    parts: list[str] = []
    if level := ep.get("level"):
        parts.append(str(level).strip())
    if metric := ep.get("metric") or ep.get("indicator"):
        parts.append(f"【指标】：{metric}")
    if config_id:
        parts.append(f"【配置ID】：{config_id}")
    if url:
        parts.append(str(url))
    parts.append(f"【会话追问】{message}")
    if page := ep.get("page"):
        parts.append(f"【情景页码】{page}")
    return "\n".join(p for p in parts if p)


def extract_episode_from_alarm_result(res: dict | None) -> dict:
    """从 Alarm 返回 dict 提炼可落库名片；关键信息不足则 {}。"""
    if not res:
        return {}
    meta = res.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    config_id = meta.get("config_id") or ""
    url = meta.get("detail_url") or ""
    if not config_id and not url:
        return {}
    return {
        "config_id": config_id or None,
        "monitor_url": url or None,
        "page": meta.get("page_count"),
        "playbook_hint": meta.get("skill_key") or None,
        "evidence_summary": (res.get("reply") or "")[:500] or None,
        "source_run_id": res.get("run_id") or meta.get("run_id"),
    }
