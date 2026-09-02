"""Day5–Day7：pipeline Replan 开关、上限与 LLM 冲突仲裁单测（不调 MCP / 浏览器 / 真实 LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.alarm import pipeline as pl
from app.agents.alarm.replan import should_fetch_page2, should_switch_playbook

def _replan_ready_state() -> dict:
    return {
        "page": 1,
        "page_size": 50,
        "fetched_pages": [1],
        "monitor_rate": {"count": 80},
        "error_analysis": {
            "total": 50,
            "uniqueUsers": 20,
            "topErrorsRaw": [{"msg": "err-A", "count": 10}],
        },
        "pagination": "browser",
        "parsed": {},
        "replans": [],
        "playbook_switched": False,
        "skill_key": "render",
        "skill_meta": {"key": "render", "type": "渲染异常"},
        "skip_reason": None,
        "monitor_detail": {"list": []},
    }


def _conflict_state() -> dict:
    """同时满足补页 + 换 playbook，触发 Day6 LLM 仲裁。"""
    state = _replan_ready_state()
    state["error_analysis"] = {
        "total": 50,
        "uniqueUsers": 20,
        "topErrorsRaw": [{"msg": "接口失败 code非1", "count": 10}],
        "pageName": "下单页",
        "errUrl": "/bff/submit",
    }
    state["monitor_detail"] = {
        "list": [{"err_msg": "接口失败", "scene": "提单", "url": "/api/order/create"}]
    }
    return state


@pytest.mark.asyncio
async def test_run_replan_loop_fetch_page2(monkeypatch):
    state = _replan_ready_state()
    fetched_pages: list[int] = []

    async def mock_fetch(s, step, *, on_progress=None):
        fetched_pages.append(int(step.get("page") or 0))
        s["fetched_pages"].append(2)
        s["page"] = 2

    async def mock_analyze(s):
        return None

    monkeypatch.setattr(pl, "_step_fetch", mock_fetch)
    monkeypatch.setattr(pl, "_step_analyze", mock_analyze)

    stages: list[str] = []

    async def on_stage(msg: str, meta: dict | None = None) -> None:
        stages.append(msg)

    await pl._run_replan_loop(state, on_stage=on_stage)

    assert fetched_pages == [2]
    assert "fetch_page2" in state["replans"]
    assert any("补拉第 2 页" in m for m in stages)


@pytest.mark.asyncio
async def test_run_replan_loop_respects_max_pages(monkeypatch):
    state = _replan_ready_state()
    state["fetched_pages"] = [1, 2]
    state["page"] = 2
    monkeypatch.setattr(pl.settings, "alarm_replan_max_pages", 2)

    async def mock_fetch(s, step, *, on_progress=None):
        raise AssertionError("不应再补页")

    monkeypatch.setattr(pl, "_step_fetch", mock_fetch)
    await pl._run_replan_loop(state)
    assert state["replans"] == []


@pytest.mark.asyncio
async def test_run_replan_loop_switch_playbook_once(monkeypatch):
    state = _replan_ready_state()
    state["error_analysis"] = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败 code非1", "count": 15}],
        "pageName": "下单页",
        "errUrl": "/bff/submit",
    }
    # 不满足补页（未满 50 条）
    monkeypatch.setattr(pl.settings, "alarm_replan_max_playbook_switch", 1)

    stages: list[str] = []

    async def on_stage(msg: str, meta: dict | None = None) -> None:
        stages.append(msg)

    await pl._run_replan_loop(state, on_stage=on_stage)

    assert state["skill_key"] == "bff"
    assert state["playbook_switched"] is True
    assert any(r.startswith("switch_playbook:") for r in state["replans"])
    assert any("更换 playbook" in m for m in stages)


@pytest.mark.asyncio
async def test_run_replan_loop_no_switch_when_max_switch_zero(monkeypatch):
    state = _replan_ready_state()
    state["error_analysis"] = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败", "count": 15}],
        "errUrl": "/bff/x",
    }
    monkeypatch.setattr(pl.settings, "alarm_replan_max_playbook_switch", 0)

    await pl._run_replan_loop(state)
    assert state["skill_key"] == "render"
    assert state["replans"] == []


@pytest.mark.asyncio
async def test_run_initial_pipeline_skips_replan_when_disabled(monkeypatch):
    monkeypatch.setattr(pl.settings, "alarm_replan_enabled", False)
    replan_calls: list[int] = []

    async def track_replan(*_a, **_kw):
        replan_calls.append(1)

    monkeypatch.setattr(pl, "_run_replan_loop", track_replan)

    async def fake_run_step(state, step, *, on_progress=None):
        sid = step.get("id")
        if sid == pl.STEP_PARSE:
            state["parsed"] = {"indicator": "测试"}
            state["config_id"] = ""
        elif sid == pl.STEP_CLASSIFY:
            state["skill_meta"] = {"key": "render", "type": "渲染异常"}
            state["skill_key"] = "render"
        elif sid == pl.STEP_FETCH:
            state["fetch_res"] = None
        elif sid == pl.STEP_ANALYZE:
            state["skip_reason"] = None
        return state

    monkeypatch.setattr(pl, "run_step", fake_run_step)

    state = await pl.run_initial_pipeline("P1 测试", stop_before_report=True)
    assert replan_calls == []
    assert state.get("replans") == []


@pytest.mark.asyncio
async def test_run_replan_loop_conflict_llm_chooses_switch(monkeypatch):
    state = _conflict_state()
    assert should_fetch_page2(
        page=1,
        monitor_rate=state["monitor_rate"],
        error_analysis=state["error_analysis"],
        pagination=state["pagination"],
    )
    assert should_switch_playbook(skill_key="render", error_analysis=state["error_analysis"]) == "bff"

    fetched_pages: list[int] = []

    async def mock_fetch(s, step, *, on_progress=None):
        fetched_pages.append(int(step.get("page") or 0))

    monkeypatch.setattr(pl, "_step_fetch", mock_fetch)
    monkeypatch.setattr(
        pl,
        "llm_pick_replan_action",
        AsyncMock(return_value="switch_playbook:bff"),
    )

    await pl._run_replan_loop(state)

    assert state["skill_key"] == "bff"
    assert state["replans"][0] == "switch_playbook:bff"
    pl.llm_pick_replan_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_replan_loop_conflict_llm_none_fallback_fetch(monkeypatch):
    state = _conflict_state()
    fetched_pages: list[int] = []

    async def mock_fetch(s, step, *, on_progress=None):
        fetched_pages.append(int(step.get("page") or 0))
        s["fetched_pages"].append(2)
        s["page"] = 2

    async def mock_analyze(s):
        return None

    monkeypatch.setattr(pl, "_step_fetch", mock_fetch)
    monkeypatch.setattr(pl, "_step_analyze", mock_analyze)
    monkeypatch.setattr(pl, "llm_pick_replan_action", AsyncMock(return_value=None))

    await pl._run_replan_loop(state)

    assert fetched_pages == [2]
    assert "fetch_page2" in state["replans"]


@pytest.mark.asyncio
async def test_run_replan_loop_conflict_llm_finish(monkeypatch):
    state = _conflict_state()
    monkeypatch.setattr(pl, "llm_pick_replan_action", AsyncMock(return_value="finish"))

    async def mock_fetch(s, step, *, on_progress=None):
        raise AssertionError("finish 时不应补页")

    monkeypatch.setattr(pl, "_step_fetch", mock_fetch)
    await pl._run_replan_loop(state)

    assert state["replans"] == []
    assert state["skill_key"] == "render"


def test_replan_rules_still_gate_fetch_and_switch():
    """上限由 pipeline 控制；规则函数保持纯判定。"""
    ea = {
        "total": 50,
        "uniqueUsers": 20,
        "topErrorsRaw": [{"msg": "a", "count": 10}],
    }
    assert should_fetch_page2(
        page=1, monitor_rate={"count": 80}, error_analysis=ea, pagination="browser"
    )
    assert should_switch_playbook(
        skill_key="render",
        error_analysis={
            "total": 20,
            "topErrorsRaw": [{"msg": "接口失败", "count": 15}],
            "errUrl": "/bff/x",
        },
    ) == "bff"
