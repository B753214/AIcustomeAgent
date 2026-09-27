from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings, settings

engine = create_async_engine(settings.POSTGRES_URI, echo=settings.DEBUG, pool_pre_ping=True)
AsyncSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_db()->AsyncGenerator[AsyncSession, None]:
    async with AsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()

async def init_db()->None:
    import app.models.sessions  # noqa: F401 — chat_* / session_summaries
    import app.models.memory_facts  # noqa: F401 — memory_facts
    import app.models.document  # noqa: F401
    import app.harness_storage.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_chat_session_columns)
        await conn.run_sync(_ensure_chat_message_columns)
        await conn.run_sync(_ensure_memory_facts_indexes)
        print("Database initialized")


def _ensure_chat_session_columns(sync_conn) -> None:
    """已有 PG 表时 create_all 不加列：补齐 M1-2 字段（幂等）。"""
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "chat_sessions" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("chat_sessions")}
    alters: list[str] = []
    if "user_id" not in existing:
        alters.append(
            "ALTER TABLE chat_sessions ADD COLUMN user_id VARCHAR(128) "
            "NOT NULL DEFAULT 'anonymous'"
        )
    if "tenant_id" not in existing:
        alters.append("ALTER TABLE chat_sessions ADD COLUMN tenant_id VARCHAR(128) NULL")
    if "status" not in existing:
        alters.append(
            "ALTER TABLE chat_sessions ADD COLUMN status VARCHAR(32) "
            "NOT NULL DEFAULT 'active'"
        )
    if "updated_at" not in existing:
        alters.append("ALTER TABLE chat_sessions ADD COLUMN updated_at TIMESTAMP NULL")
    for sql in alters:
        sync_conn.execute(text(sql))
    if alters and "user_id" in "".join(alters):
        sync_conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id ON chat_sessions (user_id)")
        )


def _ensure_chat_message_columns(sync_conn) -> None:
    """已有 PG 表时 create_all 不加列：补齐 M2-1 字段（幂等）。"""
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "chat_messages" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("chat_messages")}
    alters: list[str] = []
    if "intent" not in existing:
        alters.append("ALTER TABLE chat_messages ADD COLUMN intent VARCHAR(64) NULL")
    if "engine" not in existing:
        alters.append("ALTER TABLE chat_messages ADD COLUMN engine VARCHAR(32) NULL")
    if "run_id" not in existing:
        alters.append("ALTER TABLE chat_messages ADD COLUMN run_id VARCHAR(36) NULL")
    if "metadata" not in existing:
        alters.append("ALTER TABLE chat_messages ADD COLUMN metadata JSON NULL")
    for sql in alters:
        sync_conn.execute(text(sql))
    sync_conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_run_id "
            "ON chat_messages (run_id)"
        )
    )


def _ensure_memory_facts_indexes(sync_conn) -> None:
    """旧唯一索引会阻止 supersede 后插入同 key；改为 partial unique。"""
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "memory_facts" not in insp.get_table_names():
        return
    # 去掉「全状态唯一」的旧索引（若存在）
    sync_conn.execute(text("DROP INDEX IF EXISTS ix_memory_facts_user_kind_key"))
    # 仅 active/candidate 唯一，允许 superseded 历史行共存
    sync_conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_facts_live_key "
            "ON memory_facts (tenant_id, user_id, kind, normalized_key) "
            "WHERE status IN ('active', 'candidate')"
        )
    )
    sync_conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_memory_facts_user_kind_key "
            "ON memory_facts (tenant_id, user_id, kind, normalized_key)"
        )
    )
