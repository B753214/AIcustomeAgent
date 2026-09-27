"""Memory-M6-RAG：检索问句改写（无 LLM 真调）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services.memory import query_rewrite as qr


@pytest.mark.asyncio
async def test_no_history_returns_original():
    assert await qr.rewrite_retrieval_query("运费谁出？", None) == "运费谁出？"
    assert await qr.rewrite_retrieval_query("运费谁出？", []) == "运费谁出？"


@pytest.mark.asyncio
async def test_disabled_skips_llm(monkeypatch):
    monkeypatch.setattr(qr.settings, "rag_query_rewrite_enabled", False)
    with patch.object(qr, "get_llm") as get_llm:
        out = await qr.rewrite_retrieval_query(
            "那运费呢？",
            [{"role": "user", "content": "订单 O-1 运费规则"}],
        )
    assert out == "那运费呢？"
    get_llm.assert_not_called()


@pytest.mark.asyncio
async def test_dict_history_rewrites():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="  订单O-1的运费规则是什么？  "))
    with patch.object(qr, "get_llm", return_value=llm):
        out = await qr.rewrite_retrieval_query(
            "那运费呢？",
            [
                {"role": "user", "content": "查一下订单 O-1"},
                {"role": "assistant", "content": "已找到订单"},
            ],
        )
    assert out == "订单O-1的运费规则是什么？"
    llm.ainvoke.assert_awaited_once()
    msgs = llm.ainvoke.await_args.args[0]
    assert "O-1" in msgs[1].content
    assert "那运费呢？" in msgs[1].content


@pytest.mark.asyncio
async def test_lc_messages_history_rewrites():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="订单O-1运费谁承担？"))
    with patch.object(qr, "get_llm", return_value=llm):
        out = await qr.rewrite_retrieval_query(
            "谁出？",
            [
                HumanMessage(content="订单 O-1 的运费"),
                AIMessage(content="运费由买家承担"),
            ],
        )
    assert out == "订单O-1运费谁承担？"
    hist_blob = llm.ainvoke.await_args.args[0][1].content
    assert "O-1" in hist_blob


@pytest.mark.asyncio
async def test_llm_error_falls_back():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(qr, "get_llm", return_value=llm):
        out = await qr.rewrite_retrieval_query(
            "那运费呢？",
            [{"role": "user", "content": "订单运费"}],
        )
    assert out == "那运费呢？"


@pytest.mark.asyncio
async def test_empty_rewrite_falls_back():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="   "))
    with patch.object(qr, "get_llm", return_value=llm):
        out = await qr.rewrite_retrieval_query(
            "那运费呢？",
            [{"role": "user", "content": "订单运费"}],
        )
    assert out == "那运费呢？"
