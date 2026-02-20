from __future__ import annotations

import bcrypt
from fastapi.testclient import TestClient

from src.api.server import DashboardServer


def test_dashboard_login_accepts_bcrypt_hash(monkeypatch):
    password = "DimaZ7188!"
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DASHBOARD_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD_HASH", hashed)
    monkeypatch.delenv("DASHBOARD_ADMIN_PASSWORD", raising=False)

    server = DashboardServer()
    client = TestClient(server.app)

    bad = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post(
        "/login",
        data={"username": "admin", "password": password},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    assert ok.headers.get("location") == "/"
