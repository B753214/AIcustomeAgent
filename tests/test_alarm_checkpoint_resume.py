"""H5-5：Alarm 幂等键 + checkpoint 恢复（不打真实 MCP/浏览器/LLM）。"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.alarm import pipeline as pl
from app.agents.alarm.runner import _checkpoint_payload, run_alarm_agent_stream
from app.agents.harness_alarm.checkpoint import ALARM_AFTER_FETCH, ALARM_BEFORE_REPORT
from app.agents.harness_alarm.executor import AlarmExecutor
from app.database import Base
from app.harness.contracts import RUN_COMPLETED, WORKFLOW_STEP, RunContext, RunRequest
from app.harness_storage import persist_load_checkpoint


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _fetch_state(**overrides: Any) -> dict:
    state = pl.initial_state("告警 config 11664")
    state["config_id"] = "11664"
    state["parsed"] = {"configId": "11664", "detailUrl": "https://x?marketConfigId=11664"}
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_step_fetch_records_idempotency_key_and_skips_second_call(monkeypatch):
    calls: list[int] = []

    async def fake_fetch(**kwargs):
        calls.append(int(kwargs.get("page") or 1))
        return {
            "channel": "mcp",
            "monitorRate": {"name": "白屏", "count": 3},
            "monitorDetail": {"list": []},
            "pageSize": 20,
        }

    monkeypatch.setattr(pl, "fetch_monitor_data", fake_fetch)

    state = _fetch_state()
    await pl._step_fetch(state, {"id": "fetch", "page": 1})
    await pl._step_fetch(state, {"id": "fetch", "page": 1})

    assert calls == [1]
    assert state["idempotency_keys"] == ["fetch:11664:p1"]
    assert 1 in state["fetched_pages"]
    assert state["fetch_res"]["channel"] == "mcp"


@pytest.mark.asyncio
async def test_step_fetch_skips_when_key_preloaded(monkeypatch):
    calls: list[int] = []

    async def fake_fetch(**_kwargs):
        calls.append(1)
        return {"channel": "mcp", "monitorRate": {}, "monitorDetail": None}

    monkeypatch.setattr(pl, "fetch_monitor_data", fake_fetch)

    state = _fetch_state(
        idempotency_keys=["fetch:11664:p1"],
        fetch_res={"channel": "mcp", "monitorRate": {"count": 1}},
        fetched_pages=[1],
    )
    msgs: list[str] = []

    async def on_progress(msg: str) -> None:
        msgs.append(msg)

    await pl._step_fetch(state, {"id": "fetch", "page": 1}, on_progress=on_progress)

    assert calls == []
    assert any("跳过重复拉取" in m for m in msgs)


@pytest.mark.asyncio
async def test_stream_resume_skips_pipeline_and_after_fetch_checkpoint(monkeypatch):
    pipeline_calls = 0

    async def boom_pipeline(*_a, **_k):
        nonlocal pipeline_calls
        pipeline_calls += 1
        raise AssertionError("resume 不应再跑 pipeline")

    monkeypatch.setattr(
        "app.agents.alarm.runner.run_initial_pipeline",
        boom_pipeline,
    )

    class _FakeLLM:
        async def astream(self, _messages):
            yield MagicMock(content="结论")
            return
            yield  # pragma: no cover

    monkeypatch.setattr("app.agents.alarm.runner._build_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "app.agents.alarm.runner._finalize_reply",
        lambda *a, **k: "最终报告",
    )
    monkeypatch.setattr(
        "app.agents.alarm.runner.load_playbook",
        lambda _key: "playbook",
    )

    resume = _checkpoint_payload(
        _fetch_state(
            skill_meta={"key": "precise", "type": "精准"},
            skill_key="precise",
            fetch_res={"channel": "mcp"},
            monitor_rate={"name": "白屏", "count": 2},
            fetch_meta={"fetch_channel": "mcp"},
            idempotency_keys=["fetch:11664:p1"],
            fetched_pages=[1],
        )
    )

    checkpoints: list[str] = []

    async def on_checkpoint(name: str, _payload: dict) -> None:
        checkpoints.append(name)

    events = [
        ev
        async for ev in run_alarm_agent_stream(
            "告警原文",
            resume=resume,
            on_checkpoint=on_checkpoint,
        )
    ]

    assert pipeline_calls == 0
    assert ALARM_AFTER_FETCH not in checkpoints
    assert ALARM_BEFORE_REPORT in checkpoints
    assert events[0]["msg"].startswith("从检查点恢复")
    assert any(e.get("type") == "done" for e in events)


@pytest.mark.asyncio
async def test_executor_resume_does_not_re_fetch(session_factory, monkeypatch):
    """同 run_id：第一次落 AFTER_FETCH；第二次 load → 不再调 pipeline/fetch。"""
    fetch_calls = 0

    async def counting_pipeline(message, **_kwargs):
        nonlocal fetch_calls
        fetch_calls += 1
        state = _fetch_state(
            message=message,
            skill_meta={"key": "precise", "type": "精准"},
            skill_key="precise",
            fetch_res={"channel": "mcp"},
            monitor_rate={"name": "白屏", "count": 2},
            fetch_meta={"fetch_channel": "mcp"},
            idempotency_keys=["fetch:11664:p1"],
            fetched_pages=[1],
        )
        return state

    class _FakeLLM:
        async def astream(self, _messages):
            yield MagicMock(content="x")
            return
            yield  # pragma: no cover

    monkeypatch.setattr(
        "app.agents.alarm.runner.run_initial_pipeline",
        counting_pipeline,
    )
    monkeypatch.setattr("app.agents.alarm.runner._build_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "app.agents.alarm.runner._finalize_reply",
        lambda *a, **k: "报告",
    )
    monkeypatch.setattr(
        "app.agents.alarm.runner.load_playbook",
        lambda _key: "pb",
    )

    run_id = "alarm-resume-1"
    req = RunRequest(
        input="告警原文",
        agent_id="alarm",
        options={"session_factory": session_factory},
    )

    # 第一次：冷启动，应跑 pipeline 一次并落库
    events1 = [
        ev
        async for ev in AlarmExecutor().astream(
            RunContext(run_id=run_id, request=req)
        )
    ]
    assert fetch_calls == 1
    assert any(e.type == RUN_COMPLETED for e in events1)
    loaded = await persist_load_checkpoint(
        session_factory, run_id, ALARM_AFTER_FETCH
    )
    assert loaded is not None
    assert "fetch:11664:p1" in (loaded.get("idempotency_keys") or [])

    # 第二次：同 run_id 恢复，不应再跑 pipeline
    events2 = [
        ev
        async for ev in AlarmExecutor().astream(
            RunContext(run_id=run_id, request=req)
        )
    ]
    assert fetch_calls == 1
    assert any(
        e.type == WORKFLOW_STEP
        and "检查点" in str((e.payload or {}).get("message") or "")
        for e in events2
    )
    assert any(e.type == RUN_COMPLETED for e in events2)
