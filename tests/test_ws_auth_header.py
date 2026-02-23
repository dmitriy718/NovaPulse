from __future__ import annotations

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.server import DashboardServer


def test_websocket_rejects_without_api_key_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("DASHBOARD_REQUIRE_API_KEY_FOR_READS", "true")
    server = DashboardServer()
    server._admin_key = "ADMIN"
    client = TestClient(server.app)

    try:
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            assert False, "expected websocket connection to fail without API key"
    except WebSocketDisconnect:
        pass


def test_websocket_accepts_header_api_key(monkeypatch):
    monkeypatch.setenv("DASHBOARD_REQUIRE_API_KEY_FOR_READS", "true")
    server = DashboardServer()
    server._admin_key = "ADMIN"
    client = TestClient(server.app)

    with client.websocket_connect("/ws/live", headers={"X-API-Key": "ADMIN"}) as ws:
        msg = ws.receive_json()
        assert msg["type"] in ("status", "update")
