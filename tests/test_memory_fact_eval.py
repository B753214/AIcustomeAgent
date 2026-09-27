"""Memory-M7-4：长期事实写入/召回评测集跑手（不调真 LLM）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schema.memory_fact import MemoryFactCandidate
from app.services.memory.context_builder import build_recent_context
from app.services.memory.fact_policy import should_persist_fact
from app.services.memory.fact_store import (
    forget_fact,
    format_facts_for_prompt,
    upsert_fact_with_supersede,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "memory_fact_eval.jsonl"


def _load_cases() -> list[dict]:
    rows: list[dict] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _fact_row(d: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=d.get("id", "f"),
        kind=d["kind"],
        normalized_key=d["normalized_key"],
        content=d["content"],
        status=d.get("status", "active"),
        importance=d.get("importance", 0),
        updated_at=datetime(2026, 1, 1),
    )


def _candidate(d: dict) -> MemoryFactCandidate:
    return MemoryFactCandidate.model_validate(
        {
            "kind": d["kind"],
            "normalized_key": d["normalized_key"],
            "content": d["content"],
            "confidence": d.get("confidence", 0.9),
            "source_type": d.get("source_type", "explicit"),
        }
    )


CASES = [c for c in _load_cases() if not c.get("skip")]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_memory_fact_eval_case(case: dict):
    cat = case["category"]
    if cat in ("write_ok", "write_reject"):
        _assert_persist(case)
    elif cat == "conflict":
        await _assert_conflict(case)
    elif cat == "forget":
        await _assert_forget(case)
    elif cat == "recall_inject":
        _assert_recall(case)
    elif cat == "isolation":
        _assert_isolation(case)
    else:
        pytest.fail(f"unknown category: {cat}")


def _assert_persist(case: dict) -> None:
    fact = case["fact"]
    ok, decision, _reason = should_persist_fact(
        kind=fact["kind"],
        normalized_key=fact["normalized_key"],
        content=fact["content"],
        source_type=fact.get("source_type", "inferred"),
        confidence=float(fact.get("confidence", 0.5)),
        sensitive=bool(fact.get("sensitive", False)),
    )
    exp = case["expect"]
    assert ok is exp["persist"]
    assert decision == exp["decision"]


async def _assert_conflict(case: dict) -> None:
    old = case["old"]
    new = case["new"]
    old_row = SimpleNamespace(
        id="old1",
        content=old["content"],
        status=old.get("status", "active"),
        kind=old["kind"],
        normalized_key=old["normalized_key"],
    )
    new_row = SimpleNamespace(
        id="new1",
        content=new["content"],
        status="active",
    )
    db = MagicMock()
    with (
        patch(
            "app.services.memory.fact_store.find_active_or_candidate",
            new_callable=AsyncMock,
            return_value=old_row,
        ),
        patch(
            "app.services.memory.fact_store.insert_fact",
            new_callable=AsyncMock,
            return_value=new_row,
        ) as mocked_insert,
        patch(
            "app.services.memory.fact_store.supersede_fact",
            new_callable=AsyncMock,
        ) as mocked_super,
    ):
        out = await upsert_fact_with_supersede("user-a", _candidate(new), db)

    exp = case["expect"]
    if exp.get("supersede_called"):
        mocked_super.assert_awaited()
        mocked_insert.assert_awaited()
    assert out.content == exp["new_content"]


async def _assert_forget(case: dict) -> None:
    rows = [_fact_row(f) for f in case["facts"]]
    target = next(r for r in rows if r.id == case["forget_id"])
    db = MagicMock()
    db.flush = AsyncMock()

    with patch(
        "app.services.memory.fact_store.get_fact",
        new_callable=AsyncMock,
        return_value=target,
    ):
        out = await forget_fact("user-a", case["forget_id"], db)

    assert out is not None
    assert out.status == case["expect"]["status_after"]

    active = [r for r in rows if r.status == "active"]
    block = format_facts_for_prompt(active)
    for needle in case["expect"].get("inject_must_not_contain", []):
        assert needle not in block


def _assert_recall(case: dict) -> None:
    facts = [_fact_row(f) for f in case["facts"]]
    if case.get("only_active"):
        facts = [f for f in facts if f.status == "active"]
    else:
        facts = [f for f in facts if f.status == "active"]

    block = format_facts_for_prompt(facts)
    exp = case["expect"]
    if exp.get("inject_empty"):
        assert block == ""
        return

    must_any = exp.get("inject_must_contain_any") or []
    if must_any:
        assert any(n in block for n in must_any), block

    if exp.get("context_has_facts_system"):
        ctx = build_recent_context(
            [{"role": "user", "content": "我叫什么？"}],
            current_message="我叫什么？",
            facts_block=block or None,
        )
        assert any(
            m.get("role") == "system" and "长期记忆" in str(m.get("content", ""))
            for m in ctx
        )


def _assert_isolation(case: dict) -> None:
    a_facts = [
        _fact_row(f)
        for f in case.get("user_a_facts", [])
        if f.get("status", "active") == "active"
    ]
    b_facts = [
        _fact_row(f)
        for f in case.get("user_b_facts", [])
        if f.get("status", "active") == "active"
    ]
    a_block = format_facts_for_prompt(a_facts)
    b_block = format_facts_for_prompt(b_facts)
    exp = case["expect"]
    for needle in exp.get("a_inject_must_contain_any", []):
        assert needle in a_block
    for needle in exp.get("b_inject_must_not_contain", []):
        assert needle not in b_block
