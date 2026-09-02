"""Day2：replan 规则单测（不调 MCP / 浏览器 / LLM）。"""
from __future__ import annotations

from app.agents.alarm.replan import should_fetch_page2, should_switch_playbook


def _full_page_analysis(*, top1_count: int = 10, unique_users: int = 20) -> dict:
    return {
        "total": 50,
        "uniqueUsers": unique_users,
        "topErrorsRaw": [
            {"msg": "err-A", "count": top1_count},
            {"msg": "err-B", "count": 8},
        ],
        "pageName": "下单页",
        "errUrl": "/api/x",
    }


# ── should_fetch_page2 ───────────────────────────────────


def test_fetch_page2_when_full_page_and_top1_weak():
    assert (
        should_fetch_page2(
            page=1,
            page_size=50,
            monitor_rate={"count": 80},
            error_analysis=_full_page_analysis(top1_count=10),
            pagination="browser",
        )
        is True
    )


def test_fetch_page2_allows_browser_only_pagination():
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 80},
            error_analysis=_full_page_analysis(top1_count=10),
            pagination="browser_only",
        )
        is True
    )


def test_fetch_page2_false_when_not_full_page():
    ea = _full_page_analysis()
    ea["total"] = 8
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 8},
            error_analysis=ea,
            pagination="browser",
        )
        is False
    )


def test_fetch_page2_false_when_already_page2():
    assert (
        should_fetch_page2(
            page=2,
            monitor_rate={"count": 80},
            error_analysis=_full_page_analysis(),
            pagination="browser",
        )
        is False
    )
    assert (
        should_fetch_page2(
            page=1,
            fetched_pages=[1, 2],
            monitor_rate={"count": 80},
            error_analysis=_full_page_analysis(),
            pagination="browser",
        )
        is False
    )


def test_fetch_page2_false_when_count_zero():
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 0},
            error_analysis=_full_page_analysis(),
            pagination="browser",
        )
        is False
    )


def test_fetch_page2_false_when_no_pagination_channel():
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 80},
            error_analysis=_full_page_analysis(),
            pagination=None,
        )
        is False
    )


def test_fetch_page2_when_few_users_and_large_count():
    # Top1 很集中（不触发占比），靠 uniqueUsers + count
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 120},
            error_analysis=_full_page_analysis(top1_count=45, unique_users=1),
            pagination="browser",
        )
        is True
    )


def test_fetch_page2_when_draft_report_weak():
    ea = _full_page_analysis(top1_count=45, unique_users=30)
    assert (
        should_fetch_page2(
            page=1,
            monitor_rate={"count": 80},
            error_analysis=ea,
            pagination="browser",
            draft_report={"evidence": ["a"], "conclusion": "短"},
        )
        is True
    )


# ── should_switch_playbook ───────────────────────────────


def test_switch_playbook_render_to_bff_by_detail():
    ea = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败 code非1", "count": 15}],
        "pageName": "下单页",
        "errUrl": "/bff/submit",
    }
    assert should_switch_playbook(skill_key="render", error_analysis=ea) == "bff"


def test_switch_playbook_respects_explicit_alarm_type():
    ea = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败", "count": 15}],
        "errUrl": "/bff/x",
    }
    assert (
        should_switch_playbook(
            skill_key="render",
            alarm_type="渲染异常",
            error_analysis=ea,
        )
        is None
    )


def test_switch_playbook_false_when_already_switched():
    ea = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败", "count": 15}],
        "errUrl": "/bff/x",
    }
    assert (
        should_switch_playbook(
            skill_key="render",
            playbook_switched=True,
            error_analysis=ea,
        )
        is None
    )


def test_switch_playbook_same_key_returns_none():
    ea = {
        "total": 20,
        "topErrorsRaw": [{"msg": "接口失败", "count": 15}],
        "errUrl": "/bff/x",
    }
    assert should_switch_playbook(skill_key="bff", error_analysis=ea) is None


# ── Day6: parse_llm_replan_choice / llm_pick_replan_action ──


from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.alarm.replan import (
    llm_pick_replan_action,
    parse_llm_replan_choice,
    replan_rules_conflict,
)


def test_parse_llm_replan_choice_valid():
    assert parse_llm_replan_choice("fetch_page2") == "fetch_page2"
    assert parse_llm_replan_choice("finish") == "finish"
    assert (
        parse_llm_replan_choice("switch_playbook", allowed_switch_key="bff")
        == "switch_playbook:bff"
    )
    assert (
        parse_llm_replan_choice("switch_playbook:bff", allowed_switch_key="bff")
        == "switch_playbook:bff"
    )


def test_parse_llm_replan_choice_rejects_bad_key():
    assert parse_llm_replan_choice("switch_playbook:ajx", allowed_switch_key="bff") is None
    assert parse_llm_replan_choice("随便说说") is None


def test_replan_rules_conflict():
    assert replan_rules_conflict(want_fetch_page2=True, switch_hint_key="bff") is True
    assert replan_rules_conflict(want_fetch_page2=False, switch_hint_key="bff") is False


@pytest.mark.asyncio
async def test_llm_pick_replan_action_parses_response():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="fetch_page2"))
    with patch("app.agents.alarm.runner._build_llm", return_value=mock_llm):
        result = await llm_pick_replan_action(
            skill_key="render",
            hint_key="bff",
            error_analysis={"total": 50, "topErrorsRaw": [{"msg": "接口失败", "count": 30}]},
            monitor_rate={"count": 80},
        )
    assert result == "fetch_page2"


@pytest.mark.asyncio
async def test_llm_pick_replan_action_returns_none_on_failure():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))
    with patch("app.agents.alarm.runner._build_llm", return_value=mock_llm):
        result = await llm_pick_replan_action(
            skill_key="render",
            hint_key="bff",
        )
    assert result is None
