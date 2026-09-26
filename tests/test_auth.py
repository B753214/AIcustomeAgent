"""P5-6 API Key 鉴权 + Memory-M1-1 X-User-Id 单元测试。"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.services.auth import get_user_id, verify_api_key
from app.services.chat import _ensure_session_id


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/protected")
    async def protected(_: None = Depends(verify_api_key)):
        return {"ok": True}

    @app.get("/public")
    async def public():
        return {"ok": True}

    @app.get("/whoami")
    async def whoami(user_id: str = Depends(get_user_id)):
        return {"user_id": user_id}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


def test_disabled_allows_without_key(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.api_key_enabled", False)
    resp = client.post("/protected", json={})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_enabled_missing_key_returns_401(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.api_key_enabled", True)
    monkeypatch.setattr("app.services.auth.settings.service_api_key", "test-secret")
    resp = client.post("/protected", json={})
    assert resp.status_code == 401
    assert "API Key" in resp.json()["detail"]


def test_enabled_wrong_key_returns_401(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.api_key_enabled", True)
    monkeypatch.setattr("app.services.auth.settings.service_api_key", "test-secret")
    resp = client.post(
        "/protected",
        json={},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_enabled_valid_key_returns_200(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.api_key_enabled", True)
    monkeypatch.setattr("app.services.auth.settings.service_api_key", "test-secret")
    resp = client.post(
        "/protected",
        json={},
        headers={"X-API-Key": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_enabled_without_service_key_returns_500(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.api_key_enabled", True)
    monkeypatch.setattr("app.services.auth.settings.service_api_key", "")
    resp = client.post(
        "/protected",
        json={},
        headers={"X-API-Key": "anything"},
    )
    assert resp.status_code == 500
    assert "SERVICE_API_KEY" in resp.json()["detail"]


def test_get_user_id_defaults_anonymous(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.require_user_id", False)
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "anonymous"


def test_get_user_id_from_header(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.require_user_id", False)
    resp = client.get("/whoami", headers={"X-User-Id": "demo-user-a"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "demo-user-a"


def test_require_user_id_missing_returns_401(client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.require_user_id", True)
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_ensure_session_id_mints_and_rejects_default():
    a = _ensure_session_id(None)
    b = _ensure_session_id("")
    c = _ensure_session_id("default")
    d = _ensure_session_id("keep-me")
    assert a and a != "default"
    assert b and b != "default"
    assert c != "default"
    assert d == "keep-me"
