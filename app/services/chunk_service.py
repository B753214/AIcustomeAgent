from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Chunk


async def save_document_with_chunks(file_name: str, hash_document: str, list_chunks: list[str], db: AsyncSession) -> None:
    document = Document(
        file_name=file_name,
        content_sha256=hash_document,
        chunk_count = len(list_chunks),
    )
    db.add(document)
    await db.flush()
    for index, chunk_text in enumerate(list_chunks):
        chunk = Chunk(
            document_id=document.id,
            chunk_index=index,
            content=chunk_text,
            title=file_name
        )
        await db.add(chunk)
    await db.flush()


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
    stmt = select(Chunk).where(Chunk.id.in_(chunk_ids))
    result = db.execute(stmt)
    return result.scalars().all()
