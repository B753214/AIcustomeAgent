import uuid

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from AICustomeRobort.app.models.sessions import ChatMessage, ChatSession


async def get_sessions(db: AsyncSession) -> list[ChatSession]:
    stmt = select(ChatSession)
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_session(db: AsyncSession) -> ChatSession:
    session = ChatSession(
        session_id=str(uuid.uuid4()),
    )
    db.add(session)
    return session

async def load_session_history(session_id: str, db: AsyncSession, max_turns: int | None = None) -> list[dict]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    if max_turns:
        stmt.limit(max_turns *2)
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

async def clear_session_history(session_id: str, db: AsyncSession) -> None:
    stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
    result = await db.execute(stmt)
    return result.rowcount or 0