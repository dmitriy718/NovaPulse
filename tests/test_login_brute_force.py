"""Tests for login brute-force protection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.server import DashboardServer


def _make_server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "correct-password")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DASHBOARD_ADMIN_PASSWORD_HASH", raising=False)
    server = DashboardServer()
    return TestClient(server.app)


def test_lockout_after_five_failures(monkeypatch):
    """After 5 failed logins, the 6th attempt should return 429."""
    client = _make_server(monkeypatch)

    for _ in range(5):
        resp = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    # 6th attempt should be locked out
    resp = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 429


def test_lockout_blocks_correct_password(monkeypatch):
    """Even correct credentials should be blocked during lockout."""
    client = _make_server(monkeypatch)

    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    # Correct password during lockout
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 429


def test_successful_login_clears_failures(monkeypatch):
    """A successful login should reset the failure counter."""
    client = _make_server(monkeypatch)

    # 4 failures (under threshold)
    for _ in range(4):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    # Successful login
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # After success, counter is reset — 4 more failures should be fine
    for _ in range(4):
        resp = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401


def test_under_threshold_still_allowed(monkeypatch):
    """Fewer than 5 failures should still allow login attempts."""
    client = _make_server(monkeypatch)

    for _ in range(4):
        resp = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    # 5th attempt with correct password should succeed
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_lockout_expires_after_window(monkeypatch):
    """After the lockout window passes, login attempts should be allowed again."""
    client = _make_server(monkeypatch)

    _time = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: _time[0])

    # 5 failures to trigger lockout
    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    # Still locked
    resp = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 429

    # Advance time past the window (300 seconds)
    _time[0] = 1301.0

    # Should be allowed again
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
