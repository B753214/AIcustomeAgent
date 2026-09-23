"""H4-1：Chat HTTP Adapter + ChatExecutor（mock run，不打真实 LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.harness.adapter.chat_http import (
    build_chat_runtime,
    chat_harness_http,
    to_chat_response,
    to_run_request,
)
from app.harness.contracts import RUN_COMPLETED, RunContext, RunRequest, RunResult
from app.harness.routing import RouteDecision
from app.agents.harness_chat.executor import ChatExecutor
from app.schemas import ChatRequest


def test_to_run_request_maps_message_and_options():
    kb, db = object(), object()
    req = to_run_request(
        ChatRequest(message="你好", session_id="s1"),
        kb=kb,
        db=db,
        agent_id="knowledge",
        route={"reason": "classify_intent", "confidence": None},
    )
    assert req.input == "你好"
    assert req.session_id == "s1"
    assert req.agent_id == "knowledge"
    assert req.caller == "api"
    assert req.options["kb"] is kb
    assert req.options["db"] is db
    assert req.options["route"]["reason"] == "classify_intent"


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


@pytest.mark.asyncio
async def test_chat_executor_maps_run_result():
    fake = {
        "reply": "hello",
        "intent": "chat",
        "sources": ["a"],
        "engine": "chat_react",
        "cache_hit": False,
        "used_crew": False,
        "meta": {"tool_calls": []},
    }
    with patch(
        "app.agents.harness_chat.executor.run",
        new=AsyncMock(return_value=fake),
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

    assert len(events) == 1
    ev = events[0]
    assert ev.type == RUN_COMPLETED
    assert ev.payload["output"] == "hello"
    assert ev.payload["sources"] == ["a"]
    assert ev.payload["metadata"]["engine"] == "chat_react"
    assert ev.payload["metadata"]["tool_calls"] == []
    mocked.assert_awaited_once_with("hi", "s1", "kb", "db")


@pytest.mark.asyncio
async def test_chat_harness_http_uses_executor():
    fake = {
        "reply": "pong",
        "intent": "chat",
        "sources": [],
        "engine": "chat_react",
        "cache_hit": False,
        "used_crew": False,
        "meta": {},
    }
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
            "app.agents.harness_chat.executor.run",
            new=AsyncMock(return_value=fake),
        ),
    ):
        resp = await chat_harness_http(
            ChatRequest(message="ping", session_id="t"),
            kb=object(),
            db=object(),
        )
    assert resp.reply == "pong"
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
            "app.agents.harness_chat.executor.run",
            new=AsyncMock(),
        ) as chat_run_mock,
    ):
        resp = await chat_harness_http(
            ChatRequest(message="如何配置？", session_id="t"),
            kb=object(),
            db=object(),
        )

    rag_mock.assert_awaited()
    chat_run_mock.assert_not_awaited()
    assert resp.reply == "kb-answer"
    assert resp.sources == ["doc#0"]
    assert resp.intent == "knowledge"
    assert resp.engine == "langchain"


@pytest.mark.asyncio
async def test_chat_harness_http_dispatches_alarm_executor():
    fake = {
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
            "app.agents.harness_alarm.executor.run_alarm_agent",
            new=AsyncMock(return_value=fake),
        ) as alarm_mock,
        patch(
            "app.agents.harness_chat.executor.run",
            new=AsyncMock(),
        ) as chat_run_mock,
    ):
        resp = await chat_harness_http(
            ChatRequest(message="告警原文", session_id="t"),
            kb=object(),
            db=object(),
        )

    alarm_mock.assert_awaited_once_with("告警原文")
    chat_run_mock.assert_not_awaited()
    assert resp.reply == "alarm-report"
    assert resp.intent == "alarm"
    assert resp.engine == "alarm"


@pytest.mark.asyncio
async def test_build_chat_runtime_falls_back_unknown_agent():
    runtime = build_chat_runtime("nope")
    assert runtime.executor.__class__.__name__ == "ChatExecutor"

