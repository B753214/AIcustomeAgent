import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped

from app.database import Base


class Document(Base):
    __tablename__ = "document"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_name: Mapped[str] = mapped_column(String(512), comment="文件名")
    content_sha256: Mapped[str] = mapped_column(String(64), comment="文件内容的sha256值")
    chunk_count: Mapped[int] = mapped_column(comment="文件内容的chunk数量")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), comment="创建时间")

class Chunk(Base):
    __tablename__ = "chunk"
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("document.id", ondelete="CASCADE"),index=True, comment="所属文档的id")
    chunk_index: Mapped[int] = mapped_column(comment="chunk的索引")
    title: Mapped[str] = mapped_column(String(512), comment="chunk的标题")
    content: Mapped[str] = mapped_column(Text, comment="chunk的内容")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), comment="创建时间")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
    )