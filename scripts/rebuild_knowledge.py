# -*- coding: utf-8 -*-
"""Inspect or rebuild the PostgreSQL + Milvus knowledge base from local files.

The default mode is read-only. Pass --apply to delete existing Document/Chunk
rows and reset the configured Milvus collection before ingesting unique files.
Chat sessions and messages are never touched.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".markdown", ".txt"}


def clean_extracted_text(text: str) -> tuple[str, int]:
    """Remove characters PostgreSQL cannot store in a text column."""
    nul_count = text.count("\x00")
    return text.replace("\x00", ""), nul_count


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_files(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda path: ("(1)" in path.name, path.name.casefold()),
    )
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in candidates:
        by_hash[file_sha256(path)].append(path)

    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for digest, paths in by_hash.items():
        canonical = paths[0]
        unique.append(
            {
                "path": canonical,
                "name": canonical.name,
                "sha256": digest,
                "size": canonical.stat().st_size,
            }
        )
        for duplicate in paths[1:]:
            duplicates.append(
                {
                    "name": duplicate.name,
                    "canonical": canonical.name,
                    "sha256": digest,
                    "size": duplicate.stat().st_size,
                }
            )
    unique.sort(key=lambda item: item["name"].casefold())
    duplicates.sort(key=lambda item: item["name"].casefold())
    return unique, duplicates


async def current_inventory() -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.database import AsyncSession
    from app.models import Chunk, Document
    from app.rag.milvus_store import COLLECTION_NAME, get_milvus_client

    async with AsyncSession() as db:
        document_count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
        chunk_count = (await db.execute(select(func.count()).select_from(Chunk))).scalar_one()
        documents = [
            {
                "id": row.id,
                "file_name": row.file_name,
                "content_sha256": row.content_sha256,
                "chunk_count": row.chunk_count,
            }
            for row in (await db.execute(select(Document).order_by(Document.file_name))).scalars().all()
        ]

    client = get_milvus_client()
    exists = client.has_collection(collection_name=COLLECTION_NAME)
    if exists:
        client.flush(collection_name=COLLECTION_NAME)
    stats = client.get_collection_stats(collection_name=COLLECTION_NAME) if exists else {}
    return {
        "postgres": {
            "documents": document_count,
            "chunks": chunk_count,
            "items": documents,
        },
        "milvus": {
            "collection": COLLECTION_NAME,
            "exists": exists,
            "rows": int(stats.get("row_count") or 0),
        },
    }


def inspect_extractability(files: list[dict[str, Any]], min_chars: int) -> list[dict[str, Any]]:
    from app.rag.loader import parse_file

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(files, 1):
        path = item["path"]
        started = time.perf_counter()
        try:
            text, nul_count = clean_extracted_text(parse_file(path))
            char_count = len(text.strip())
            error = None
        except Exception as exc:
            char_count = 0
            nul_count = 0
            error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "name": item["name"],
                "chars": char_count,
                "eligible": char_count >= min_chars and error is None,
                "removed_nul_chars": nul_count,
                "error": error,
                "parse_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        print(f"[{index}/{len(files)}] {item['name']}: {char_count} chars")
    return rows


async def purge_knowledge() -> None:
    from sqlalchemy import delete

    from app.database import AsyncSession
    from app.models import Chunk, Document
    from app.rag.milvus_store import COLLECTION_NAME, ensure_collection, get_milvus_client

    client = get_milvus_client()
    if client.has_collection(collection_name=COLLECTION_NAME):
        client.drop_collection(collection_name=COLLECTION_NAME)
    ensure_collection()

    async with AsyncSession() as db:
        await db.execute(delete(Chunk))
        await db.execute(delete(Document))
        await db.commit()


def _batched(values: list[Any], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def preflight_embedding() -> dict[str, Any]:
    """Validate the configured embedding service before destructive rebuild steps."""
    from app.config import settings
    from app.rag.milvus_store import DIM
    from app.rag.retriever import build_embedding

    started = time.perf_counter()
    embedder = build_embedding()
    vector = await asyncio.to_thread(embedder.embed_query, "知识库重建连通性检查")
    if len(vector) != DIM:
        raise RuntimeError(f"embedding dimension mismatch: {len(vector)} != {DIM}")
    return {
        "model": settings.AIROBOT_EMBEDDING_MODEL,
        "dimension": len(vector),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def ingest_one(path: Path, *, embedding_batch_size: int) -> dict[str, Any]:
    from app.database import AsyncSession
    from app.rag.loader import parse_file
    from app.rag.milvus_store import COLLECTION_NAME, DIM, get_milvus_client
    from app.rag.retriever import build_embedding, split_text
    from app.services.chunk_service import save_document_with_chunks

    started = time.perf_counter()
    text, nul_count = clean_extracted_text(parse_file(path))
    split_docs = split_text(path.name, text)
    texts = [doc.page_content for doc in split_docs if doc.page_content.strip()]
    if not texts:
        raise ValueError("no extractable text chunks")

    embedder = build_embedding()
    vectors: list[list[float]] = []
    for batch in _batched(texts, embedding_batch_size):
        batch_vectors = await asyncio.to_thread(embedder.embed_documents, batch)
        vectors.extend(batch_vectors)
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding count mismatch: {len(vectors)} != {len(texts)}")
    if vectors and len(vectors[0]) != DIM:
        raise RuntimeError(f"embedding dimension mismatch: {len(vectors[0])} != {DIM}")

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    client = get_milvus_client()
    document_id: str | None = None
    async with AsyncSession() as db:
        try:
            document_id, rows = await save_document_with_chunks(path.name, content_hash, texts, db)
            payload = [
                {
                    "id": row.id,
                    "chunk_id": row.id,
                    "doc_id": document_id,
                    "vector": vector,
                }
                for row, vector in zip(rows, vectors)
            ]
            for batch in _batched(payload, 200):
                client.upsert(collection_name=COLLECTION_NAME, data=batch)
            await db.commit()
        except Exception:
            await db.rollback()
            if document_id:
                try:
                    client.delete(
                        collection_name=COLLECTION_NAME,
                        filter=f'doc_id == "{document_id}"',
                    )
                except Exception:
                    pass
            raise

    return {
        "name": path.name,
        "chars": len(text),
        "chunks": len(texts),
        "removed_nul_chars": nul_count,
        "elapsed_sec": round(time.perf_counter() - started, 2),
    }


async def async_main(args: argparse.Namespace) -> int:
    from app.database import engine

    engine.echo = False
    source = Path(args.source).resolve()
    unique, duplicates = discover_files(source)
    before = await current_inventory()
    print(
        f"发现 {len(unique) + len(duplicates)} 个文件，"
        f"唯一内容 {len(unique)} 份，重复副本 {len(duplicates)} 份"
    )
    print(
        f"当前数据库：{before['postgres']['documents']} documents / "
        f"{before['postgres']['chunks']} chunks；Milvus {before['milvus']['rows']} rows"
    )
    for item in duplicates:
        print(f"重复跳过：{item['name']} -> {item['canonical']}")

    extraction = inspect_extractability(unique, args.min_chars)
    eligible_names = {row["name"] for row in extraction if row["eligible"]}
    eligible = [item for item in unique if item["name"] in eligible_names]
    skipped = [row for row in extraction if not row["eligible"]]

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = BASE_DIR / "eval" / "reports" / f"knowledge_rebuild_{timestamp}.json"
    report: dict[str, Any] = {
        "source": str(source),
        "apply": args.apply,
        "before": before,
        "unique_files": [{k: v for k, v in item.items() if k != "path"} for item in unique],
        "duplicates": duplicates,
        "extraction": extraction,
        "skipped": skipped,
        "ingested": [],
        "failures": [],
    }

    if not args.apply:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"只读检查完成：{report_path}")
        return 0

    print("执行 embedding 服务预检，确认成功后才会清空旧知识库...")
    from app.config import settings as app_settings

    try:
        report["embedding_preflight"] = await preflight_embedding()
    except Exception as exc:
        report["embedding_preflight"] = {
            "model": app_settings.AIROBOT_EMBEDDING_MODEL,
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["after"] = before
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"embedding 预检失败，旧知识库保持不变：{report['embedding_preflight']['error']}")
        print(f"重建报告：{report_path}")
        return 1

    print("开始重置 Document/Chunk 与 Milvus collection...")
    await purge_knowledge()
    for index, item in enumerate(eligible, 1):
        try:
            result = await ingest_one(
                item["path"], embedding_batch_size=args.embedding_batch_size
            )
            report["ingested"].append(result)
            print(
                f"[{index}/{len(eligible)}] 已入库 {result['name']}："
                f"{result['chunks']} chunks / {result['elapsed_sec']}s"
            )
        except Exception as exc:
            failure = {"name": item["name"], "error": f"{type(exc).__name__}: {exc}"}
            report["failures"].append(failure)
            print(f"[{index}/{len(eligible)}] 入库失败 {item['name']}：{failure['error']}")
            if not args.continue_on_error:
                break

    report["after"] = await current_inventory()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"重建报告：{report_path}")
    return 1 if report["failures"] else 0


def main() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="重建 PostgreSQL + Milvus 知识库")
    parser.add_argument("--source", default=str(BASE_DIR / "knowledge"))
    parser.add_argument("--apply", action="store_true", help="确认清空旧知识并执行入库")
    parser.add_argument("--min-chars", type=int, default=100)
    parser.add_argument("--embedding-batch-size", type=int, default=10)
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
