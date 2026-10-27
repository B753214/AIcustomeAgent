from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.agents.alarm import fetcher, replan, runner
from app.agents.alarm.report import analyze_error_details


@pytest.mark.asyncio
async def test_next_page_bypasses_mcp(monkeypatch):
    mcp = AsyncMock(return_value={"channel": "mcp"})
    browser = AsyncMock(return_value={"channel": "browser", "page": 2})
    monkeypatch.setattr(fetcher, "_fetch_via_mcp", mcp)
    monkeypatch.setattr("app.agents.alarm.browser.fetch_via_browser", browser)
    monkeypatch.setattr(fetcher.settings, "alarm_browser_enabled", True)
    result = await fetcher.fetch_monitor_data(market_config_id="123", raw_url="https://x", page=2)
    mcp.assert_not_awaited()
    assert result["page"] == 2
    assert browser.await_args.kwargs["page"] == 2


@pytest.mark.asyncio
async def test_mcp_first_batch_is_bounded(monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_via_mcp", AsyncMock(return_value={
        "channel": "mcp", "monitorDetail": [{"id": i} for i in range(50)],
    }))
    result = await fetcher.fetch_monitor_data(market_config_id="123", page_size=20)
    assert len(result["monitorDetail"]) == 20
    assert result["has_more"] is True


def test_merge_deduplicates_and_analysis_includes_new_pages():
    from app.agents.alarm.format import format_detail_for_llm
    first = [{"id": i, "err_msg": "old"} for i in range(50)]
    second = [{"id": 0, "err_msg": "old"}, {"id": 51, "err_msg": "new"}]
    merged = fetcher.merge_monitor_details(first, second)
    analysis = analyze_error_details(merged)
    assert analysis["total"] == 51
    assert any(e["msg"] == "new" for e in analysis["topErrorsRaw"])
    assert "错误:new" in format_detail_for_llm(merged)


@pytest.mark.asyncio
async def test_assessment_validates_structured_response(monkeypatch):
    from langchain_core.messages import AIMessage
    llm = MagicMock()
    structured = MagicMock()
    decision = replan.EvidenceDecision(action="fetch_next_page", reason="样本不足",
        missing_evidence=["其他用户"], expected_gain="判断影响范围")
    structured.ainvoke = AsyncMock(return_value={
        "raw": AIMessage(content=""), "parsed": decision, "parsing_error": None,
    })
    llm.with_structured_output.return_value = structured
    monkeypatch.setattr(runner, "_build_llm", lambda: llm)
    result = await replan.assess_evidence({"monitor_detail": [], "skill_key": "precise"})
    assert result.action == "fetch_next_page"
    llm.with_structured_output.assert_called_once_with(
        replan.EvidenceDecision, method="function_calling", include_raw=True,
    )
    structured.ainvoke.assert_awaited_once()


@pytest.mark.parametrize("raw", ["fetch_page2", '{"action":"fetch_next_page","reason":"more"}',
                                  '{"action":"execute","reason":"x"}'])
def test_invalid_or_unjustified_decision_rejected(raw):
    with pytest.raises(ValidationError):
        replan.EvidenceDecision.model_validate_json(raw)


def test_report_includes_missing_evidence(monkeypatch):
    monkeypatch.setattr(runner, "load_playbook", lambda _: "playbook")
    messages, *_ = runner._assemble("alarm", {}, {"key": "precise"}, "123", None,
        evidence_context={"stop_reason": "need_other_evidence", "missing_evidence": ["stack"]})
    assert "stack" in messages[-1].content
    assert "待确认" in messages[-1].content
