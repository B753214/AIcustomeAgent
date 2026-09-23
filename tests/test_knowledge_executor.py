"""H4-2：KnowledgeExecutor（mock aanswer_with_rag，不打真实检索/LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.harness_knowledge.executor import KnowledgeExecutor
from app.harness.contracts import RUN_COMPLETED, RUN_FAILED, RunContext, RunRequest


@pytest.mark.asyncio
async def test_knowledge_executor_maps_rag_result():
    with patch(
        "app.agents.harness_knowledge.executor.aanswer_with_rag",
        new=AsyncMock(return_value=("根据文档，答案是 X", ["doc.md#0"])),
    ) as mocked:
        ctx = RunContext(
            run_id="r1",
            request=RunRequest(
                input="什么是 X？",
                agent_id="knowledge",
                options={"kb": "fake-kb", "history": []},
            ),
        )
        events = [ev async for ev in KnowledgeExecutor().astream(ctx)]

    assert len(events) == 1
    ev = events[0]
    assert ev.type == RUN_COMPLETED
    assert ev.run_id == "r1"
    assert ev.payload["output"] == "根据文档，答案是 X"
    assert ev.payload["sources"] == ["doc.md#0"]
    assert ev.payload["metadata"]["intent"] == "knowledge"
    assert ev.payload["metadata"]["engine"] == "langchain"
    mocked.assert_awaited_once_with("什么是 X？", "fake-kb", history=[])


@pytest.mark.asyncio
async def test_knowledge_executor_yields_run_failed_on_error():
    with patch(
        "app.agents.harness_knowledge.executor.aanswer_with_rag",
        new=AsyncMock(side_effect=RuntimeError("rag down")),
    ):
        ctx = RunContext(
            run_id="r2",
            request=RunRequest(
                input="q",
                agent_id="knowledge",
                options={"kb": object()},
            ),
        )
        events = [ev async for ev in KnowledgeExecutor().astream(ctx)]

    assert len(events) == 1
    ev = events[0]
    assert ev.type == RUN_FAILED
    assert ev.payload["message"] == "rag down"
