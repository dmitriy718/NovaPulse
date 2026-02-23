from __future__ import annotations

from src.api.server import DashboardServer


def test_dashboard_default_allowed_origins_are_local_only(monkeypatch):
    monkeypatch.delenv("DASHBOARD_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("DASHBOARD_PUBLIC_ORIGIN", raising=False)

    server = DashboardServer()

    assert all(
        origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")
        for origin in server._allowed_origins
    )
    assert "https://nova.horizonsvc.com" not in server._allowed_origins


def test_dashboard_public_origin_is_normalized_and_allowed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", "https://nova.horizonsvc.com/")
    monkeypatch.setenv("DASHBOARD_PUBLIC_ORIGIN", "https://nova.horizonsvc.com/")

    server = DashboardServer()

    assert "https://nova.horizonsvc.com" in server._allowed_origins
    assert "https://nova.horizonsvc.com/" not in server._allowed_origins
