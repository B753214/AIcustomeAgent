"""会话读写：一律按 user_id + session_id 隔离。

session_id 仍为全局主键（一会话一主人）；换 user 读同一 session_id → 视为不存在。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.sessions import ChatMessage, ChatSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm_user(user_id: str | None) -> str:
    u = (user_id or "").strip()
    return u if u else "anonymous"


async def get_sessions(db: AsyncSession, user_id: str) -> list[ChatSession]:
    uid = _norm_user(user_id)
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.user_id == uid,
            ChatSession.status != "deleted",
        )
        .order_by(ChatSession.updated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_session(
    session_id: str,
    user_id: str,
    db: AsyncSession,
) -> ChatSession | None:
    """只读：必须同时匹配所有者。"""
    uid = _norm_user(user_id)
    stmt = select(ChatSession).where(
        ChatSession.session_id == session_id,
        ChatSession.user_id == uid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_session(
    session_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> ChatSession:
    uid = _norm_user(user_id)
    now = _utcnow()
    session = ChatSession(
        session_id=session_id,
        user_id=uid,
        tenant_id=tenant_id,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def _fetch_by_session_id(
    db: AsyncSession,
    session_id: str,
) -> ChatSession | None:
    """只按 session_id 查（冲突后再读必须能看到任意主人的行）。"""
    stmt = select(ChatSession).where(ChatSession.session_id == session_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_session(
    session_id: str,
    user_id: str,
    db: AsyncSession,
) -> ChatSession | None:
    """按 session_id 查找；若存在但属于他人 → None；不存在则创建。

    并发首次创建同一 session_id 时：捕获主键冲突，SAVEPOINT 回滚后以库为准再读。
    """
    uid = _norm_user(user_id)
    session = await _fetch_by_session_id(db, session_id)


    if session is not None:
        if session.user_id != uid:
            return None
        if session.status != "active":
            raise PermissionError("session is not active")
        session.updated_at = _utcnow()
        return session

    try:
        async with db.begin_nested():
            return await create_session(session_id, uid, db)
    except IntegrityError:
        pass

    session = await _fetch_by_session_id(db, session_id)
    if session is None:
        raise RuntimeError(f"session create raced but row missing: {session_id}")
    if session.user_id != uid:
        return None
    if session.status != "active":
        raise PermissionError("session is not active")
    session.updated_at = _utcnow()
    return session


async def load_session_history(
    session_id: str,
    user_id: str,
    db: AsyncSession,
    max_turns: int = settings.memory_max_turns,
    *,
    create_if_missing: bool = True,
) -> list[dict]:
    uid = _norm_user(user_id)
    if create_if_missing:
        session = await get_or_create_session(session_id, uid, db)
    else:
        session = await get_session(session_id, uid, db)
    if not session:
        return []

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
    )
    if max_turns:
        stmt = stmt.limit(max_turns * 2)
    result = await db.execute(stmt)
    messages = list(reversed(result.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in messages]


async def save_message(
    session_id: str,
    role: str,
    content: str,
    db: AsyncSession,
) -> ChatMessage:
    message = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(message)
    return message


async def save_turn(
    session_id: str,
    user_id: str,
    user_text: str,
    assistant_text: str,
    db: AsyncSession,
) -> None:
    session = await get_or_create_session(session_id, user_id, db)
    if session is None:
        raise PermissionError(
            f"session {session_id!r} belongs to another user"
        )
    if session.status != "active":
        raise PermissionError(
            f"session {session_id!r} is not active"
        )
    await save_message(session_id, "user", user_text, db)
    await save_message(session_id, "assistant", assistant_text, db)
    session.updated_at = _utcnow()


async def clear_session_history(
    session_id: str,
    user_id: str,
    db: AsyncSession,
) -> int:
    session = await get_session(session_id, user_id, db)
    if session is None:
        return 0
    stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
    result = await db.execute(stmt)
    session.updated_at = _utcnow()
    return int(result.rowcount or 0)

async def end_session(session_id: str, user_id: str, db: AsyncSession) -> ChatSession | None:
    session = await get_session(session_id, user_id, db)
    if session is None:
        return None
    if session.status == "deleted":
        return None
    now = _utcnow()
    session.status = "ended"
    session.ended_at = now
    session.updated_at = now
    return session


async def archive_session(session_id: str, user_id: str, db: AsyncSession) -> ChatSession | None:
    session = await get_session(session_id, user_id, db)
    if session is None:
        return None
    if session.status == "deleted":
        return None
    now = _utcnow()
    session.status = "archived"
    session.updated_at = now
    if session.ended_at is None:
        session.ended_at = now
    return session


async def soft_delete_session(
    session_id: str,
    user_id: str,
    db: AsyncSession,
) -> ChatSession | None:
    """软删：status=deleted，列表不可见；消息保留待 M1-5 清理。"""
    session = await get_session(session_id, user_id, db)
    if session is None:
        return None
    now = _utcnow()
    session.status = "deleted"
    session.updated_at = now
    if session.ended_at is None:
        session.ended_at = now
    return session
