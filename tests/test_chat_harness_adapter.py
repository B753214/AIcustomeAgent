"""H2-3：Chat HTTP Adapter + Echo 路径。"""
from __future__ import annotations

import pytest

from app.harness.adapter.chat_http import chat_harness_http, to_chat_response, to_run_request
from app.harness.contracts import RunResult
from app.schemas import ChatRequest


def test_to_run_request_maps_message():
    req = to_run_request(ChatRequest(message="你好", session_id="s1"))
    assert req.input == "你好"
    assert req.session_id == "s1"
    assert req.agent_id == "chat"
    assert req.caller == "api"


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
async def test_chat_harness_http_echo():
    resp = await chat_harness_http(ChatRequest(message="ping", session_id="t"))
    assert resp.reply == "harness:ping"
    assert resp.engine == "harness"
