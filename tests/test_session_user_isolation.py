"""Memory-M1-2：会话 user_id 隔离。"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.sessions import ChatSession
from app.services.session_service import (
    _norm_user,
    create_session,
    get_or_create_session,
    get_session,
    get_sessions,
)


def test_norm_user_defaults_anonymous():
    assert _norm_user(None) == "anonymous"
    assert _norm_user("  ") == "anonymous"
    assert _norm_user("alice") == "alice"


@pytest.mark.asyncio
async def test_get_or_create_rejects_other_users_session():
    db = AsyncMock()
    owned = ChatSession(session_id="s1", user_id="user-a", status="active")
    result = MagicMock()
    result.scalar_one_or_none.return_value = owned
    db.execute = AsyncMock(return_value=result)

    got = await get_or_create_session("s1", "user-b", db)
    assert got is None


@pytest.mark.asyncio
async def test_get_or_create_returns_own_session():
    db = AsyncMock()
    owned = ChatSession(session_id="s1", user_id="user-a", status="active")
    result = MagicMock()
    result.scalar_one_or_none.return_value = owned
    db.execute = AsyncMock(return_value=result)

    got = await get_or_create_session("s1", "user-a", db)
    assert got is owned
    assert got.user_id == "user-a"


@pytest.mark.asyncio
async def test_get_session_filters_by_user():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    assert await get_session("s1", "user-b", db) is None
    # 确认 where 被调用（至少执行了查询）
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_create_session_sets_user_id():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    sid = str(uuid.uuid4())
    sess = await create_session(sid, "user-a", db)
    assert sess.session_id == sid
    assert sess.user_id == "user-a"
    assert sess.status == "active"
    db.add.assert_called_once()
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_get_or_create_integrity_error_rereads_own_row(monkeypatch):
    """并发：INSERT 撞主键后应再读并返回已有行，不向外抛。"""
    db = AsyncMock()
    owned = ChatSession(session_id="s1", user_id="user-a", status="active")

    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    found = MagicMock()
    found.scalar_one_or_none.return_value = owned
    db.execute = AsyncMock(side_effect=[empty, found])

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    db.begin_nested = MagicMock(return_value=_Nested())

    async def _boom(*_a, **_k):
        raise IntegrityError("statement", {}, Exception("dup"))

    monkeypatch.setattr(
        "app.services.session_service.create_session",
        _boom,
    )

    got = await get_or_create_session("s1", "user-a", db)
    assert got is owned
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_or_create_rejects_ended_own_session():
    db = AsyncMock()
    ended = ChatSession(session_id="s1", user_id="user-a", status="ended")
    result = MagicMock()
    result.scalar_one_or_none.return_value = ended
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(PermissionError, match="not active"):
        await get_or_create_session("s1", "user-a", db)


@pytest.mark.asyncio
async def test_end_archive_soft_delete():
    from app.services.session_service import end_session, archive_session, soft_delete_session

    db = AsyncMock()
    sess = ChatSession(session_id="s1", user_id="u1", status="active")
    result = MagicMock()
    result.scalar_one_or_none.return_value = sess
    db.execute = AsyncMock(return_value=result)

    ended = await end_session("s1", "u1", db)
    assert ended is not None
    assert ended.status == "ended"
    assert ended.ended_at is not None

    sess.status = "active"
    sess.ended_at = None
    archived = await archive_session("s1", "u1", db)
    assert archived is not None
    assert archived.status == "archived"
    assert not hasattr(archived, "archived_at") or getattr(archived, "archived_at", None) is None

    sess.status = "active"
    deleted = await soft_delete_session("s1", "u1", db)
    assert deleted is not None
    assert deleted.status == "deleted"


@pytest.mark.asyncio
async def test_save_turn_rejects_non_active():
    from app.services.session_service import save_turn

    db = AsyncMock()
    ended = ChatSession(session_id="s1", user_id="u1", status="ended")
    result = MagicMock()
    result.scalar_one_or_none.return_value = ended
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(PermissionError, match="not active"):
        await save_turn("s1", "u1", "hi", "hello", db)

@pytest.mark.asyncio
async def test_get_sessions_filters_user():
    db = AsyncMock()
    rows = [
        ChatSession(session_id="a", user_id="u1"),
        ChatSession(session_id="b", user_id="u1"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)

    got = await get_sessions(db, "u1")
    assert len(got) == 2
    assert all(s.user_id == "u1" for s in got)


@pytest.mark.asyncio
async def test_get_or_create_integrity_error_other_owner_returns_none(monkeypatch):
    db = AsyncMock()
    other = ChatSession(session_id="s1", user_id="user-b", status="active")

    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    found = MagicMock()
    found.scalar_one_or_none.return_value = other
    db.execute = AsyncMock(side_effect=[empty, found])

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    db.begin_nested = MagicMock(return_value=_Nested())

    async def _boom(*_a, **_k):
        from sqlalchemy.exc import IntegrityError

        raise IntegrityError("statement", {}, Exception("dup"))

    monkeypatch.setattr(
        "app.services.session_service.create_session",
        _boom,
    )

    got = await get_or_create_session("s1", "user-a", db)
    assert got is None
