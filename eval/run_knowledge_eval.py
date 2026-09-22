# -*- coding: utf-8 -*-
"""Generate grounded QA cases and compare RAG retrieval strategies."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from pydantic import BaseModel, Field  # noqa: E402


logger = logging.getLogger(__name__)


class GeneratedQA(BaseModel):
    question: str = Field(description="不包含文档名、可由给定资料明确回答的问题")
    reference: str = Field(description="完全依据资料的简洁标准答案")
    keywords: list[str] = Field(description="答案中的2到5个关键短语")


class GeneratedQASet(BaseModel):
    items: list[GeneratedQA]


class AnswerGrade(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


async def generate_dataset(
    path: Path, questions_per_doc: int, document_limit: int = 0
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.database import AsyncSession, engine
    from app.models import Chunk, Document
    from app.rag.retriever import build_llm

    engine.echo = False
    prompt = (
        "你是RAG评测数据生成器。仅依据给定资料生成{count}个高质量问题。"
        "问题不能出现文档名，不能依赖资料外知识，答案必须能被资料直接支持；"
        "优先选择有区分度的技术概念、设计原因、流程或约束，不要问空泛的总结题。\n\n"
        "资料：\n{context}"
    )
    generator = build_llm().with_structured_output(GeneratedQASet)
    rows: list[dict[str, Any]] = []
    async with AsyncSession() as db:
        documents = list((await db.execute(select(Document).order_by(Document.file_name))).scalars())
        if document_limit > 0:
            documents = documents[:document_limit]
        equivalent_titles: dict[str, list[str]] = defaultdict(list)
        for document in documents:
            equivalent_titles[document.content_sha256].append(document.file_name)
        for index, document in enumerate(documents, 1):
            chunks = list(
                (
                    await db.execute(
                        select(Chunk)
                        .where(Chunk.document_id == document.id)
                        .order_by(Chunk.chunk_index)
                    )
                ).scalars()
            )
            if not chunks:
                continue
            positions = sorted({0, len(chunks) // 2, len(chunks) - 1})
            context = "\n\n".join(chunks[pos].content[:2200] for pos in positions)[:6500]
            try:
                result = await generator.ainvoke(
                    prompt.format(count=questions_per_doc, context=context)
                )
                items = result.items[:questions_per_doc]
            except Exception as exc:
                print(f"[{index}/{len(documents)}] 生成失败 {document.file_name}: {exc}")
                continue
            for item_index, item in enumerate(items, 1):
                rows.append(
                    {
                        "id": f"doc-{index:03d}-{item_index}",
                        "category": Path(document.file_name).stem,
                        "question": item.question.strip(),
                        "reference": item.reference.strip(),
                        "keywords": item.keywords,
                        "expected_document": document.file_name,
                        "expected_documents": equivalent_titles[document.content_sha256],
                    }
                )
            print(f"[{index}/{len(documents)}] {document.file_name}: {len(items)} questions")
    write_jsonl(path, rows)
    print(f"生成评测集：{path}（{len(rows)} 条）")
    return rows


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * ratio) - 1)], 2)


def _rank_for_document(chunks: list[Any], expected_documents: list[str]) -> int | None:
    for index, chunk in enumerate(chunks, 1):
        if chunk.title in expected_documents:
            return index
    return None


async def retrieve(
    kb,
    mode: str,
    question: str,
    top_k: int,
    rerank_candidates: int,
    rerank_top_k: int,
):
    if mode == "vector":
        return await kb.search_vector(question, top_k)
    if mode == "bm25":
        return kb.search_bm25(question, top_k)
    if mode == "hybrid":
        return await kb.search_hybrid(
            question, top_k, vector_top_k=top_k, bm25_top_k=top_k
        )
    if mode == "rerank":
        candidates = await kb.search_hybrid(
            question,
            rerank_candidates,
            vector_top_k=rerank_candidates,
            bm25_top_k=rerank_candidates,
        )
        chunks, applied, error = kb.rerank_documents(
            question, candidates, rerank_top_k
        )
        if not applied:
            raise RuntimeError(f"rerank was not applied: {error or 'unknown error'}")
        return chunks
    raise ValueError(f"unsupported mode: {mode}")


async def grade_answer(question: str, reference: str, answer: str) -> AnswerGrade:
    from app.rag.retriever import build_llm

    judge = build_llm().with_structured_output(AnswerGrade)
    prompt = (
        "你是RAG回答评测员。比较标准答案和实际回答，只评价正确性、完整性和是否有资料依据。"
        "5=完全正确完整，4=基本正确，3=部分正确，2=错误较多，1=错误或答非所问。\n\n"
        f"问题：{question}\n标准答案：{reference}\n实际回答：{answer}"
    )
    for attempt in range(1, 4):
        try:
            return await judge.ainvoke(prompt)
        except Exception:
            if attempt == 3:
                raise
            logger.warning("LLM judge structured output failed; retrying (%s/3)", attempt)
            await asyncio.sleep(0.5 * attempt)
    raise RuntimeError("LLM judge retry loop exited unexpectedly")


async def evaluate(args: argparse.Namespace, items: list[dict[str, Any]]) -> dict[str, Any]:
    from app.config import settings
    from app.database import AsyncSession, engine
    from app.rag.retriever import KnowledgeBase, RAG_PROMPT, build_llm

    engine.echo = False
    async with AsyncSession() as db:
        kb = KnowledgeBase(db)
        await kb.build_index()
        mode_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        answer_rows: list[dict[str, Any]] = []

        for index, item in enumerate(items, 1):
            for mode in args.modes:
                result_top_k = args.rerank_top_k if mode == "rerank" else args.top_k
                started = time.perf_counter()
                chunks = (
                    await retrieve(
                        kb,
                        mode,
                        item["question"],
                        args.top_k,
                        args.rerank_candidates,
                        args.rerank_top_k,
                    )
                )[:result_top_k]
                latency = round((time.perf_counter() - started) * 1000, 2)
                expected_documents = item.get("expected_documents") or [item["expected_document"]]
                rank = _rank_for_document(chunks, expected_documents)
                mode_rows[mode].append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "expected_document": item["expected_document"],
                        "rank": rank,
                        "hit": rank is not None,
                        "latency_ms": latency,
                        "retrieved": [chunk.title for chunk in chunks],
                    }
                )

            if args.answers:
                chunks = (
                    await retrieve(
                        kb,
                        "rerank",
                        item["question"],
                        args.top_k,
                        args.rerank_candidates,
                        args.rerank_top_k,
                    )
                )[: args.rerank_top_k]
                contexts = [chunk.content for chunk in chunks]
                if contexts:
                    answer_message = await (
                        RAG_PROMPT | build_llm()
                    ).ainvoke(
                        {
                            "context": "\n\n".join(contexts),
                            "question": item["question"],
                            "history": [],
                        }
                    )
                    answer = str(getattr(answer_message, "content", answer_message))
                else:
                    answer = "未检索到相关知识，请尝试其他关键词。"
                grade = await grade_answer(item["question"], item["reference"], answer)
                answer_rows.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "expected_document": item["expected_document"],
                        "reference": item["reference"],
                        "answer": answer,
                        "sources": [chunk.title for chunk in chunks],
                        "source_hit": _rank_for_document(
                            chunks,
                            item.get("expected_documents") or [item["expected_document"]],
                        )
                        is not None,
                        "judge_score": grade.score,
                        "judge_reason": grade.reason,
                    }
                )
            print(f"[{index}/{len(items)}] {item['id']} {item['question']}")

    retrieval_summary: dict[str, Any] = {}
    for mode, rows in mode_rows.items():
        result_top_k = args.rerank_top_k if mode == "rerank" else args.top_k
        latencies = [row["latency_ms"] for row in rows]
        ranks = [row["rank"] for row in rows if row["rank"] is not None]
        retrieval_summary[mode] = {
            "cases": len(rows),
            "top_k": result_top_k,
            "hit_at_k": round(len(ranks) / len(rows), 4) if rows else 0.0,
            "mrr": round(sum(1 / rank for rank in ranks) / len(rows), 4) if rows else 0.0,
            "latency_p50_ms": _percentile(latencies, 0.5),
            "latency_p95_ms": _percentile(latencies, 0.95),
        }

    answer_summary = None
    if answer_rows:
        answer_summary = {
            "cases": len(answer_rows),
            "avg_judge_score": round(
                sum(row["judge_score"] for row in answer_rows) / len(answer_rows), 2
            ),
            "source_hit_rate": round(
                sum(1 for row in answer_rows if row["source_hit"]) / len(answer_rows), 4
            ),
        }
    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dataset": str(args.dataset),
            "total": len(items),
            "top_k": args.top_k,
            "rerank_candidates": args.rerank_candidates,
            "rerank_top_k": args.rerank_top_k,
            "modes": args.modes,
            "embedding_model": settings.AIROBOT_EMBEDDING_MODEL,
            "rerank_model": settings.rerank_model,
            "rerank_enabled": settings.rerank_enabled,
        },
        "retrieval_summary": retrieval_summary,
        "answer_summary": answer_summary,
        "retrieval_samples": mode_rows,
        "answer_samples": answer_rows,
    }


def write_report(report: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Knowledge RAG 评测报告", "", f"- 样本数：{report['meta']['total']}", f"- Embedding：{report['meta']['embedding_model']}", f"- Reranker：{report['meta']['rerank_model']}（enabled={report['meta']['rerank_enabled']}）", f"- 召回 Top-K：{report['meta']['top_k']}", f"- 重排：候选 {report['meta']['rerank_candidates']} 条，输出 {report['meta']['rerank_top_k']} 条", "", "## 检索对比", "", "| 模式 | K | Hit@K | MRR | P50(ms) | P95(ms) |", "|---|---:|---:|---:|---:|---:|"]
    for mode, item in report["retrieval_summary"].items():
        lines.append(
            f"| {mode} | {item['top_k']} | {item['hit_at_k']:.2%} | {item['mrr']:.4f} | "
            f"{item['latency_p50_ms']} | {item['latency_p95_ms']} |"
        )
    if report.get("answer_summary"):
        item = report["answer_summary"]
        lines.extend(
            [
                "",
                "## 回答质量",
                "",
                f"- LLM Judge 平均分：{item['avg_judge_score']} / 5",
                f"- 正确来源命中率：{item['source_hit_rate']:.2%}",
            ]
        )
    failures = []
    for mode, rows in report["retrieval_samples"].items():
        for row in rows:
            if not row["hit"]:
                failures.append((mode, row))
    lines.extend(["", "## 未命中样本", ""])
    if failures:
        for mode, row in failures[:30]:
            lines.append(
                f"- `{mode}` / `{row['id']}`：{row['question']}（期望 {row['expected_document']}）"
            )
    else:
        lines.append("无。")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def async_main(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset)
    if args.generate or not dataset_path.exists():
        items = await generate_dataset(dataset_path, args.questions_per_doc, args.limit)
    else:
        items = load_jsonl(dataset_path)
    if args.limit > 0:
        items = items[: args.limit]
    if not items:
        print("评测集为空")
        return 2
    report = await evaluate(args, items)
    out = Path(args.out) if args.out else BASE_DIR / "eval" / "reports" / f"knowledge_eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    write_report(report, out)
    print(json.dumps({"retrieval": report["retrieval_summary"], "answers": report["answer_summary"]}, ensure_ascii=False, indent=2))
    print(f"报告：{out} / {out.with_suffix('.md')}")
    return 0


def main() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Knowledge 文档 RAG 分策略评测")
    parser.add_argument("--dataset", default=str(BASE_DIR / "eval" / "dataset" / "knowledge_qa.jsonl"))
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--questions-per-doc", type=int, default=1)
    parser.add_argument("--modes", nargs="+", choices=["vector", "bm25", "hybrid", "rerank"], default=["vector", "bm25", "hybrid", "rerank"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rerank-candidates", type=int, default=20)
    parser.add_argument("--rerank-top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
