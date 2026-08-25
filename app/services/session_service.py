import uuid

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.sessions import ChatMessage, ChatSession


async def get_sessions(db: AsyncSession) -> list[ChatSession]:
    stmt = select(ChatSession)
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_session(session_id: str, db: AsyncSession) -> ChatSession:
    session = ChatSession(
        session_id=session_id,
    )
    db.add(session)
    return session

async def load_session_history(session_id: str, db: AsyncSession, max_turns: int = settings.memory_max_turns) -> list[dict]:
    session = await get_or_create_session(session_id, db)
    if not session:
        return []
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    if max_turns:
        stmt = stmt.limit(max_turns *2)
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [{"role": message.role, "content": message.content} for message in messages]

async def save_message(
        session_id: str,
        role: str,
        content: str,
        db: AsyncSession
)->ChatMessage:
    message: ChatMessage = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(message)
    return message

async def save_turn(
        session_id: str,
        user_text: str,
        assistant_text: str,
        db: AsyncSession
)->None:
    await get_or_create_session(session_id, db)
    await save_message(session_id, "user", user_text, db)
    await save_message(session_id, "assistant", assistant_text, db)


async def clear_session_history(session_id: str, db: AsyncSession) -> None:
    stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
    result = await db.execute(stmt)
    return result.rowcount or 0

async def get_or_create_session(session_id: str, db: AsyncSession) -> ChatSession:
    stmt = select(ChatSession).where(ChatSession.session_id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session:
        return session

    return await create_session(session_id,db)
