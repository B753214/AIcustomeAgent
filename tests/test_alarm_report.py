"""Day9：playbook / format / report 单测。"""
from __future__ import annotations

from app.agents.alarm.format import format_detail_for_llm
from app.agents.alarm.load_playbooks import load_playbook, truncate_playbook
from app.agents.alarm.report import (
    analyze_error_details,
    build_skip_report,
    build_url_report,
    parse_ai_result,
    should_skip_analysis,
)


def test_load_playbook_keys():
    for key in ("ajx", "bff", "render", "voc", "precise", "generic"):
        text = load_playbook(key)
        assert text
        assert "排查" in text or "Playbook" in text or "playbook" in text.lower() or "专家" in text


def test_load_playbook_bff_specific():
    text = load_playbook("bff")
    assert "BFF" in text


def test_truncate_playbook():
    long = "排查要点\n" + ("x" * 5000) + "\n## 其他\n" + ("y" * 1000)
    out = truncate_playbook(long, 3000)
    assert len(out) <= 3000


def test_format_detail_for_llm():
    detail = {
        "list": [
            {"time": "t1", "err_msg": "E1", "url": "/api/a", "uid": "u1"},
            {"time": "t2", "err_msg": "E1", "uid": "u2"},
        ]
    }
    text = format_detail_for_llm(detail)
    assert "E1" in text
    assert "1." in text


def test_analyze_error_details_top():
    detail = {
        "list": [
            {"err_msg": "CODE_X", "uid": "1", "url": "/pay"},
            {"err_msg": "CODE_X", "uid": "2", "url": "/pay"},
            {"err_msg": "CODE_Y", "uid": "3"},
        ]
    }
    ana = analyze_error_details(detail)
    assert ana is not None
    assert ana["total"] == 3
    assert ana["uniqueUsers"] == 3
    assert "CODE_X" in ana["topErrors"][0]
    assert ana["errUrl"] == "/pay"


def test_should_skip_when_zero():
    assert should_skip_analysis({"name": "BFF", "count": 0})
    assert should_skip_analysis({"count": 3}) is None
    assert should_skip_analysis(None) is None


def test_parse_ai_result():
    ai = """排查结论
BFF 异常
证据链
1. 失败 10 次
2. 错误码 CODE_X
修复建议
短期：查日志
长期：加降级
"""
    parsed = parse_ai_result(ai)
    assert "BFF" in parsed["conclusion"]
    assert len(parsed["evidence"]) == 2
    assert "查日志" in parsed["shortTerm"]


def test_build_url_report_with_ai():
    rate = {"name": "填单BFF", "count": 5, "yesterdayCount": 1, "lastWeekCount": 2}
    ai = """排查结论
提交失败
证据链
1. 错误集中
修复建议
短期：重启
长期：优化
"""
    md = build_url_report(
        rate,
        None,
        "https://info-plate.fc.alibaba-inc.com/x",
        ai,
        channel="mcp",
        skill={"type": "BFF错误", "skill": "wuying-bff", "key": "bff"},
    )
    assert "排查报告" in md
    assert "BFF错误" in md
    assert "提交失败" in md
    assert "mcp" in md


def test_build_skip_report():
    text = build_skip_report("监控A 当前无失败", monitor_url="https://x", channel="browser")
    assert "当前无失败" in text
    assert "browser" in text
