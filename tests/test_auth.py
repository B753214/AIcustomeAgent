"""P5-6 API Key 鉴权单元测试。"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.services.auth import verify_api_key


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/protected")
    async def protected(_: None = Depends(verify_api_key)):
        return {"ok": True}

    @app.get("/public")
    async def public():
        return {"ok": True}

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
