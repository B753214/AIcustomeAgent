"""H3-2：ModelGateway 按角色取模型（mock，不打真实 API）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.harness.model.model_gateway import ModelGateway, ROLE_MODELS


@patch("app.harness.model.model_gateway.get_llm")
def test_get_known_roles_pass_role_default_model(mock_get_llm: MagicMock):
    fake = MagicMock(name="llm")
    mock_get_llm.return_value = fake
    gw = ModelGateway()

    for role in ("worker", "router", "judge"):
        mock_get_llm.reset_mock()
        assert gw.get(role) is fake
        mock_get_llm.assert_called_once()
        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["model"] == ROLE_MODELS[role]
        assert kwargs["base_url"] == settings.AIROBOT_LLM_BASE_URL


@patch("app.harness.model.model_gateway.get_llm")
def test_get_overrides_win_over_role_default(mock_get_llm: MagicMock):
    mock_get_llm.return_value = MagicMock()
    gw = ModelGateway()
    gw.get("worker", model="tiny-model", temperature=0)
    kwargs = mock_get_llm.call_args.kwargs
    assert kwargs["model"] == "tiny-model"
    assert kwargs["temperature"] == 0


def test_get_unknown_role_raises():
    gw = ModelGateway()
    with pytest.raises(ValueError, match="not in"):
        gw.get("nope")


def test_resolve_model_and_custom_role_map():
    gw = ModelGateway(role_models={"worker": "w-model", "router": "r-model"})
    assert gw.resolve_model("worker") == "w-model"
    assert gw.resolve_model("router") == "r-model"
    with pytest.raises(ValueError):
        gw.resolve_model("judge")


@patch("app.harness.model.model_gateway.get_llm")
def test_usage_counts_get_calls(mock_get_llm: MagicMock):
    mock_get_llm.return_value = MagicMock()
    gw = ModelGateway()
    gw.get("worker")
    gw.get("router")
    snap = gw.usage_snapshot()
    assert snap["calls"] == 2
    assert snap["by_role"]["worker"] == 1
    assert snap["by_role"]["router"] == 1
