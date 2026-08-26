from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Chunk


async def list_all_chunks(db: AsyncSession) -> list[Chunk]:
    """全量加载所有 chunk（用于服务启动时构建 BM25 索引）。"""
    stmt = select(Chunk).order_by(Chunk.document_id.asc(), Chunk.chunk_index.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def document_exists_by_name(file_name: str, db: AsyncSession) -> bool:
    """按原始文件名判断示例库 / 文档是否已导入。"""
    stmt = select(Document.id).where(Document.file_name == file_name).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def save_document_with_chunks(
    file_name: str,
    hash_document: str,
    list_chunks: list[str],
    db: AsyncSession,
) -> tuple[str, list[Chunk]]:
    document = Document(
        file_name=file_name,
        content_sha256=hash_document,
        chunk_count=len(list_chunks),
    )
    db.add(document)
    rows: list[Chunk] = []
    await db.flush()
    for index, chunk_text in enumerate(list_chunks):
        row = Chunk(
            document_id=document.id,
            chunk_index=index,
            content=chunk_text,
            title=file_name,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return document.id, rows


async def list_chunk_texts(document_id: str, db: AsyncSession) -> list[str]:
    stmt = (
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index.asc())
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()
    return [c.content for c in chunks]


async def get_chunks_by_ids(chunk_ids: list[str], db: AsyncSession) -> list[Chunk]:
    if not chunk_ids:
        return []
    stmt = select(Chunk).where(Chunk.id.in_(chunk_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())
