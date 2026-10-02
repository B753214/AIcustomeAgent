"""Memory-M7-5：长对话 / 跨会话 / 追问 / 隔离回归跑手（不调真 LLM）。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.sessions import ChatMessage
from app.schema.memory_summary import SessionSummaryPayload
from app.services.chat import _ensure_session_id
from app.services.memory.alarm_episode import merge_alarm_followup
from app.services.memory.context_builder import build_recent_context
from app.services.memory.fact_store import format_facts_for_prompt
from app.services.memory import query_rewrite as qr
from app.services.memory.summary_service import format_summary, split_for_summary
from app.services.semantic_cache import SemanticCache

_FIXTURE = Path(__file__).parent / "fixtures" / "memory_regression.jsonl"


def _load_cases() -> list[dict]:
    rows: list[dict] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


CASES = _load_cases()


def _history_from_turns(turns: list) -> list[dict]:
    """turns: [[user, assistant|null], ...] → flat messages with ids."""
    out: list[dict] = []
    i = 0
    for pair in turns:
        u = pair[0]
        a = pair[1] if len(pair) > 1 else None
        out.append({"id": f"m{i}", "role": "user", "content": u})
        i += 1
        if a is not None:
            out.append({"id": f"m{i}", "role": "assistant", "content": a})
            i += 1
    return out


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


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_memory_regression_case(case: dict):
    cat = case["category"]
    if cat == "long_summary":
        _assert_long_summary(case)
    elif cat == "cross_session_facts":
        _assert_cross_session(case)
    elif cat == "alarm_followup":
        _assert_alarm(case)
    elif cat == "rag_rewrite":
        await _assert_rag_rewrite(case)
    elif cat == "cache_isolation":
        _assert_cache(case)
    elif cat == "session_id":
        _assert_session_id(case)
    elif cat == "observability":
        _assert_observability(case)
    else:
        pytest.fail(f"unknown category: {cat}")


def _assert_long_summary(case: dict) -> None:
    history = _history_from_turns(case["history_turns"])
    old, recent = split_for_summary(
        history,
        min_turns=case.get("min_turns", 3),
        keep_turns=case.get("keep_turns", 2),
    )
    assert old, "应触发摘要切分"
    blob = " ".join(m["content"] for m in old)
    for needle in case["expect"].get("old_must_contain", []):
        assert needle in blob

    summary = SessionSummaryPayload.model_validate(case["summary"])
    ctx = build_recent_context(
        recent,
        current_message=recent[-1]["content"] if recent else "",
        summary=summary,
        max_turns=None,
    )
    text = format_summary(summary)
    joined = " ".join(str(m.get("content", "")) for m in ctx)
    must_any = case["expect"].get("context_must_contain_any") or []
    assert any(n in joined or n in text for n in must_any), joined

    if case["expect"].get("summary_before_recent"):
        assert ctx[0]["role"] == "system"
        assert "会话摘要" in str(ctx[0]["content"])


def _assert_cross_session(case: dict) -> None:
    a_facts = [
        _fact_row(f)
        for f in case["session_1_facts"]
        if f.get("status", "active") == "active"
    ]
    block = format_facts_for_prompt(a_facts)
    must_any = case["expect"].get("inject_must_contain_any") or []
    assert any(n in block for n in must_any)

    # 另一用户：无事实 → 注入不得含隐私
    other = format_facts_for_prompt([])
    for needle in case["expect"].get("other_user_must_not_contain", []):
        assert needle not in other

    ctx = build_recent_context(
        [{"role": "user", "content": case["session_2_probe"]}],
        current_message=case["session_2_probe"],
        facts_block=block,
        max_turns=None,
    )
    assert any("长期记忆" in str(m.get("content", "")) for m in ctx if m.get("role") == "system")


def _assert_alarm(case: dict) -> None:
    text = merge_alarm_followup(case["message"], case["episode"])
    for needle in case["expect"].get("must_contain_any", []):
        assert needle in text


async def _assert_rag_rewrite(case: dict) -> None:
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(
        return_value=SimpleNamespace(content=case["llm_rewrite"])
    )
    with patch.object(qr, "get_llm", return_value=llm):
        out = await qr.rewrite_retrieval_query(case["question"], case["history"])
    must_any = case["expect"].get("rewritten_must_contain_any") or []
    assert any(n in out for n in must_any), out


def _assert_cache(case: dict) -> None:
    cache = SemanticCache(cache_threshold=0.75, lexical_threshold=0.5)
    vec = case["vec"]
    cache.put(
        vec,
        case["query"],
        {"reply": "退货指引", "intent": "knowledge"},
        user_id=case["put_user"],
    )
    hit = cache.get(vec, case["query"], user_id=case["get_user_hit"])
    miss = cache.get(vec, case["query"], user_id=case["get_user_miss"])
    assert (hit is not None) is case["expect"]["hit_for_owner"]
    assert (miss is None) is case["expect"]["miss_for_other"]


def _assert_session_id(case: dict) -> None:
    for raw in case["inputs"]:
        sid = _ensure_session_id(raw)
        assert sid.lower() != "default"
        # 空/default 应发号成 UUID
        if raw is None or not str(raw).strip() or str(raw).strip().lower() == "default":
            uuid.UUID(sid)


def _assert_observability(case: dict) -> None:
    cols = {c.name for c in ChatMessage.__table__.columns}
    for name in case["expect"].get("model_fields", []):
        assert name in cols, f"missing column {name}"
