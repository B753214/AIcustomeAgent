"""H4-2：Knowledge HTTP Adapter（mock RAG，不打真实检索/LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.harness.adapter.knowledge_http import (
    knowledge_harness_http,
    to_retrieval_response,
    to_run_request,
)
from app.harness.contracts import RunResult


def test_to_run_request_maps_query_and_kb():
    kb = object()
    req = to_run_request("什么是 RAG？", kb)  # type: ignore[arg-type]
    assert req.input == "什么是 RAG？"
    assert req.agent_id == "knowledge"
    assert req.caller == "api"
    assert req.options["kb"] is kb


def test_to_retrieval_response_maps_result():
    result = RunResult(
        status="succeeded",
        output="答案",
        sources=["doc.md#0"],  # type: ignore[arg-type]
    )
    resp = to_retrieval_response(result)
    assert resp == {"reply": "答案", "sources": ["doc.md#0"]}


def test_to_retrieval_response_includes_error():
    result = RunResult(
        status="failed",
        output="",
        error={"message": "boom"},
    )
    resp = to_retrieval_response(result)
    assert resp["reply"] == ""
    assert resp["error"] == {"message": "boom"}


@pytest.mark.asyncio
async def test_knowledge_harness_http_uses_executor():
    with patch(
        "app.agents.harness_knowledge.executor.aanswer_with_rag",
        new=AsyncMock(return_value=("pong", ["s1"])),
    ):
        resp = await knowledge_harness_http("ping", kb=object())  # type: ignore[arg-type]
    assert resp["reply"] == "pong"
    assert resp["sources"] == ["s1"]
