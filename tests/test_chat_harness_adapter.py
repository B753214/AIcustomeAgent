"""H4-1：Chat HTTP Adapter + ChatExecutor（mock run_astream，不打真实 LLM）。"""
from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.harness_chat.executor import ChatExecutor
from app.harness.adapter.chat_http import (
    build_chat_runtime,
    chat_harness_http,
    to_chat_response,
    to_run_request,
)
from app.harness.adapter.sse_map import run_event_to_sse_dict
from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    WORKFLOW_STEP,
    RunContext,
    RunEvent,
    RunRequest,
    RunResult,
)
from app.harness.routing import RouteDecision
from app.schemas import ChatRequest


def test_to_run_request_maps_message_and_options():
    kb, db = object(), object()
    req = to_run_request(
        ChatRequest(message="你好", session_id="s1"),
        kb=kb,
        db=db,
        agent_id="knowledge",
        route={"reason": "classify_intent", "confidence": None},
        user_id="user-a",
    )
    assert req.input == "你好"
    assert req.session_id == "s1"
    assert req.agent_id == "knowledge"
    assert req.caller == "api"
    assert req.options["kb"] is kb
    assert req.options["db"] is db
    assert req.options["session_factory"] is not None
    assert req.options["route"]["reason"] == "classify_intent"
    assert req.options["user_id"] == "user-a"


def test_to_run_request_mints_session_when_missing_or_default():
    minted = to_run_request(ChatRequest(message="hi", session_id=None))
    assert minted.session_id
    assert minted.session_id != "default"
    banned = to_run_request(ChatRequest(message="hi", session_id="default"))
    assert banned.session_id != "default"


def test_to_chat_response_maps_result_fields():
    result = RunResult(
        status="succeeded",
        output="hi",
        sources=[{"title": "doc1"}],
        metadata={"intent": "chat", "engine": "harness", "cache_hit": True},
        usage={"tokens": 3},
    )
    resp = to_chat_response(result)
    assert resp.reply == "hi"
    assert resp.intent == "chat"
    assert resp.engine == "harness"
    assert resp.cache_hit is True
    assert resp.sources == ["doc1"]
    assert resp.meta.get("usage") == {"tokens": 3}


def test_run_event_to_sse_dict_mapping():
    assert (
        run_event_to_sse_dict(
            RunEvent(type=RUN_STARTED, run_id="r", sequence=0, payload={})
        )
        is None
    )
    assert run_event_to_sse_dict(
        RunEvent(
            type=MODEL_TOKEN,
            run_id="r",
            sequence=1,
            payload={"content": "你"},
        )
    ) == {
        "type": "model.token",
        "run_id": "r",
        "sequence": 1,
        "content": "你",
    }
    assert run_event_to_sse_dict(
        RunEvent(
            type=WORKFLOW_STEP,
            run_id="r",
            sequence=2,
            payload={"stage": "intent", "message": "ok", "ok": True, "ms": 1},
        )
    ) == {
        "type": "workflow.step",
        "run_id": "r",
        "sequence": 2,
        "stage": "intent",
        "message": "ok",
        "ok": True,
        "ms": 1,
    }
    assert run_event_to_sse_dict(
        RunEvent(
            type=RUN_COMPLETED,
            run_id="r",
            sequence=3,
            payload={
                "output": "你好",
                "sources": ["a"],
                "metadata": {"intent": "chat", "engine": "harness", "cache_hit": False},
            },
        )
    ) == {
        "type": "run.completed",
        "run_id": "r",
        "sequence": 3,
        "output": "你好",
        "sources": ["a"],
        "metadata": {"intent": "chat", "engine": "harness", "cache_hit": False},
    }
    assert run_event_to_sse_dict(
        RunEvent(
            type=RUN_FAILED,
            run_id="r",
            sequence=4,
            payload={"message": "boom"},
        )
    ) == {
        "type": "run.failed",
        "run_id": "r",
        "sequence": 4,
        "message": "boom",
    }


async def _fake_run_astream(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict]:
    yield {"type": "stage", "stage": "intent", "msg": "意图识别为 chat", "ms": 1, "ok": True}
    yield {"type": "token", "content": "hel"}
    yield {"type": "token", "content": "lo"}
    yield {
        "type": "done",
        "reply": "hello",
        "intent": "chat",
        "sources": ["a"],
        "engine": "chat_react",
        "cache_hit": False,
        "used_crew": False,
        "meta": {"tool_calls": []},
    }


@pytest.mark.asyncio
async def test_chat_executor_maps_run_astream_chunks():
    with patch(
        "app.agents.harness_chat.executor.run_astream",
        new=_fake_run_astream,
    ) as mocked:
        ctx = RunContext(
            run_id="r1",
            request=RunRequest(
                input="hi",
                session_id="s1",
                agent_id="chat",
                options={"kb": "kb", "db": "db"},
            ),
        )
        events = [ev async for ev in ChatExecutor().astream(ctx)]

    assert [e.type for e in events] == [WORKFLOW_STEP, MODEL_TOKEN, MODEL_TOKEN, RUN_COMPLETED]
    assert events[0].payload["stage"] == "intent"
    assert events[0].payload["message"] == "意图识别为 chat"
    assert events[1].payload["content"] == "hel"
    assert events[2].payload["content"] == "lo"
    done = events[-1]
    assert done.type == RUN_COMPLETED
    assert done.run_id == "r1"
    assert done.payload["output"] == "hello"
    assert done.payload["sources"] == ["a"]
    assert done.payload["metadata"]["engine"] == "chat_react"
    assert done.payload["metadata"]["tool_calls"] == []
    assert mocked is _fake_run_astream


@pytest.mark.asyncio
async def test_chat_harness_http_uses_executor():
    with (
        patch(
            "app.harness.adapter.chat_http.classify",
            new=AsyncMock(
                return_value=RouteDecision(
                    agent_id="chat",
                    reason="classify_intent",
                    confidence=None,
                )
            ),
        ),
        patch(
            "app.agents.harness_chat.executor.run_astream",
            new=_fake_run_astream,
        ),
        # to_run_request 默认挂了真实 PG session_factory；单测跳过落库
        patch("app.harness.runtime.agent_runtime.persist_run_start", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_event", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_run_end", new=AsyncMock()),
    ):
        resp = await chat_harness_http(
            ChatRequest(message="ping", session_id="t"),
            kb=object(),
            db=object(),
        )
    assert resp.reply == "hello"
    assert resp.engine == "chat_react"
    assert resp.intent == "chat"


@pytest.mark.asyncio
async def test_chat_harness_http_applies_router_agent_id():
    with (
        patch(
            "app.harness.adapter.chat_http.classify",
            new=AsyncMock(
                return_value=RouteDecision(
                    agent_id="knowledge",
                    reason="classify_intent",
                    confidence=0.9,
                )
            ),
        ) as classify_mock,
        patch(
            "app.harness.adapter.chat_http.build_chat_runtime",
        ) as build_mock,
    ):
        runtime = AsyncMock()
        runtime.execute = AsyncMock(
            return_value=RunResult(
                status="succeeded",
                output="from-kb",
                sources=["doc.md#0"],
                metadata={"intent": "knowledge", "engine": "langchain"},
            )
        )
        build_mock.return_value = runtime
        resp = await chat_harness_http(
            ChatRequest(message="如何配置？", session_id="t"),
            kb=object(),
            db=object(),
        )

    classify_mock.assert_awaited_once()
    build_mock.assert_called_once_with("knowledge")
    run_req = runtime.execute.await_args.args[0]
    assert run_req.agent_id == "knowledge"
    assert run_req.options["route"]["reason"] == "classify_intent"
    assert run_req.options["route"]["confidence"] == 0.9
    assert resp.reply == "from-kb"
    assert resp.intent == "knowledge"


@pytest.mark.asyncio
async def test_chat_harness_http_dispatches_knowledge_executor():
    with (
        patch(
            "app.harness.adapter.chat_http.classify",
            new=AsyncMock(
                return_value=RouteDecision(
                    agent_id="knowledge",
                    reason="classify_intent",
                )
            ),
        ),
        patch(
            "app.agents.harness_knowledge.executor.aanswer_with_rag",
            new=AsyncMock(return_value=("kb-answer", ["doc#0"])),
        ) as rag_mock,
        patch(
            "app.agents.harness_chat.executor.run_astream",
            new=AsyncMock(),
        ) as chat_stream_mock,
        patch("app.harness.runtime.agent_runtime.persist_run_start", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_event", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_run_end", new=AsyncMock()),
    ):
        resp = await chat_harness_http(
            ChatRequest(message="如何配置？", session_id="t"),
            kb=object(),
            db=object(),
        )

    rag_mock.assert_awaited()
    chat_stream_mock.assert_not_called()
    assert resp.reply == "kb-answer"
    assert resp.sources == ["doc#0"]
    assert resp.intent == "knowledge"
    assert resp.engine == "langchain"


@pytest.mark.asyncio
async def test_chat_harness_http_dispatches_alarm_executor():
    async def fake_alarm_stream(*_a, **_k):
        yield {
            "type": "done",
            "reply": "alarm-report",
            "intent": "alarm",
            "sources": ["mon#1"],
            "engine": "alarm",
            "cache_hit": False,
            "skip": False,
            "meta": {},
        }

    with (
        patch(
            "app.harness.adapter.chat_http.classify",
            new=AsyncMock(
                return_value=RouteDecision(
                    agent_id="alarm",
                    reason="is_alarm_message",
                    confidence=1.0,
                )
            ),
        ),
        patch(
            "app.agents.harness_alarm.executor.run_alarm_agent_stream",
            new=fake_alarm_stream,
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_load_checkpoint",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_checkpoint",
            new=AsyncMock(),
        ),
        patch(
            "app.agents.harness_chat.executor.run_astream",
            new=AsyncMock(),
        ) as chat_stream_mock,
        patch("app.harness.runtime.agent_runtime.persist_run_start", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_event", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_run_end", new=AsyncMock()),
    ):
        resp = await chat_harness_http(
            ChatRequest(message="告警原文", session_id="t"),
            kb=object(),
            db=object(),
        )

    chat_stream_mock.assert_not_called()
    assert resp.reply == "alarm-report"
    assert resp.intent == "alarm"
    assert resp.engine == "alarm"


@pytest.mark.asyncio
async def test_build_chat_runtime_falls_back_unknown_agent():
    runtime = build_chat_runtime("nope")
    assert runtime.executor.__class__.__name__ == "ChatExecutor"
