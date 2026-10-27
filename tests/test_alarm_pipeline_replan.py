"""LLM evidence decisions and bounded pagination, without external services."""
from unittest.mock import AsyncMock
import pytest
from app.agents.alarm import pipeline as pl
from app.agents.alarm.replan import EvidenceDecision


def state():
    s = pl.initial_state("alarm")
    s.update(config_id="123", parsed={"detailUrl": "https://monitor", "alarmType": "render"},
             skill_key="render", fetched_pages=[1], page=1, pagination="browser",
             monitor_detail={"list": [{"id": "1", "err_msg": "err"}]},
             error_analysis={"total": 1}, fetch_res={"channel": "browser"},
             monitor_rate={"count": 100}, last_fetch_ok=True, has_more=True)
    return s


def decision(action="fetch_next_page"):
    return EvidenceDecision(action=action, reason="need more users", missing_evidence=["user samples"],
                            expected_gain="confirm scope")


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(pl.settings, "alarm_browser_enabled", True)
    monkeypatch.setattr(pl.settings, "alarm_replan_max_pages", 3)
    monkeypatch.setattr(pl.settings, "alarm_replan_max_playbook_switch", 0)


@pytest.mark.asyncio
async def test_fetches_multiple_pages_then_finishes(monkeypatch):
    s = state()
    judge = AsyncMock(side_effect=[decision(), decision(), decision("finish")])
    monkeypatch.setattr(pl, "assess_evidence", judge)
    calls = []
    async def fetch(s, step, **kwargs):
        calls.append(step["page"])
        s["fetched_pages"].append(step["page"])
        s["monitor_detail"]["list"].append({"id": str(step["page"]), "err_msg": "new"})
    monkeypatch.setattr(pl, "_step_fetch", fetch)
    await pl._run_replan_loop(s)
    assert calls == [2, 3]
    assert s["evidence_stop_reason"] == "finish"
    assert len(s["evidence_decisions"]) == 3


@pytest.mark.parametrize("action", ["finish", "need_other_evidence"])
@pytest.mark.asyncio
async def test_no_fetch_when_model_does_not_request_it(monkeypatch, action):
    s = state()
    monkeypatch.setattr(pl, "assess_evidence", AsyncMock(return_value=decision(action)))
    fetch = AsyncMock()
    monkeypatch.setattr(pl, "_step_fetch", fetch)
    await pl._run_replan_loop(s)
    fetch.assert_not_awaited()
    assert s["evidence_stop_reason"] == action


@pytest.mark.parametrize("condition,reason", [("limit", "page_limit"), ("end", "no_more_pages"),
                                            ("unavailable", "pagination_unavailable")])
@pytest.mark.asyncio
async def test_guards_override_model(monkeypatch, condition, reason):
    s = state()
    if condition == "limit":
        monkeypatch.setattr(pl.settings, "alarm_replan_max_pages", 1)
    elif condition == "end":
        s["has_more"] = False
    else:
        monkeypatch.setattr(pl.settings, "alarm_browser_enabled", False)
    monkeypatch.setattr(pl, "assess_evidence", AsyncMock(return_value=decision()))
    fetch = AsyncMock()
    monkeypatch.setattr(pl, "_step_fetch", fetch)
    await pl._run_replan_loop(s)
    fetch.assert_not_awaited()
    assert s["evidence_stop_reason"] == reason


@pytest.mark.asyncio
async def test_assessment_failure_stops_without_fetch(monkeypatch):
    s = state()
    monkeypatch.setattr(pl, "assess_evidence", AsyncMock(side_effect=ValueError("bad JSON")))
    fetch = AsyncMock()
    monkeypatch.setattr(pl, "_step_fetch", fetch)
    await pl._run_replan_loop(s)
    fetch.assert_not_awaited()
    assert s["evidence_stop_reason"] == "assessment_failed"


@pytest.mark.asyncio
async def test_no_new_evidence_stops_loop(monkeypatch):
    s = state()
    judge = AsyncMock(return_value=decision())
    monkeypatch.setattr(pl, "assess_evidence", judge)
    monkeypatch.setattr(pl, "_step_fetch", AsyncMock())
    await pl._run_replan_loop(s)
    assert s["evidence_stop_reason"] == "no_new_evidence"
    judge.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_page_keeps_prior_evidence_and_can_retry(monkeypatch):
    s = state()
    previous = s["fetch_res"]
    monkeypatch.setattr(pl, "fetch_monitor_data", AsyncMock(return_value=None))
    await pl._step_fetch(s, {"page": 2})
    assert s["fetch_res"] is previous
    assert s["monitor_detail"]["list"][0]["id"] == "1"
    assert s["fetched_pages"] == [1]
    assert "fetch:123:p2" not in s["idempotency_keys"]
    assert not s["last_fetch_ok"]


@pytest.mark.asyncio
async def test_evaluation_timeout_is_bounded(monkeypatch):
    import asyncio
    s = state()
    monkeypatch.setattr(pl.settings, "alarm_replan_time_budget_sec", 0.01)
    async def slow(s):
        await asyncio.sleep(1)
        return decision()
    monkeypatch.setattr(pl, "assess_evidence", slow)
    await pl._run_replan_loop(s)
    assert s["evidence_stop_reason"] == "assessment_failed"


@pytest.mark.asyncio
async def test_disabled_replan_does_not_call_model(monkeypatch):
    monkeypatch.setattr(pl.settings, "alarm_replan_enabled", False)
    async def step(s, step, **kwargs):
        s.update(state())
    judge = AsyncMock()
    monkeypatch.setattr(pl, "run_step", step)
    monkeypatch.setattr(pl, "assess_evidence", judge)
    await pl.run_initial_pipeline("alarm", stop_before_report=True)
    judge.assert_not_awaited()
