from __future__ import annotations

import asyncio
import tempfile

from fastapi.testclient import TestClient

from src.api.server import DashboardServer
from src.core.config import BotConfig
from src.core.database import DatabaseManager


class _FakeStripeService:
    def __init__(self):
        self.webhook_secret = "whsec_test"
        self.enabled = True
        self.calls = []

    def set_db(self, db):
        self._db = db

    def has_plan(self, plan: str) -> bool:
        return plan in ("free", "pro")

    def create_checkout_session(
        self,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
        customer_id: str | None = None,
        plan: str = "pro",
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "plan": plan,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": customer_email,
                "customer_id": customer_id,
            }
        )
        return {"url": "https://checkout.stripe.test/cs_123", "session_id": "cs_123", "plan": plan}


def _make_server(db: DatabaseManager):
    server = DashboardServer()
    fake_stripe = _FakeStripeService()
    server.set_stripe_service(fake_stripe)
    engine = type(
        "E",
        (),
        {
            "db": db,
            "config": BotConfig(),
            "mode": "paper",
        },
    )()
    server.set_bot_engine(engine)
    return server, fake_stripe


def test_billing_checkout_free_plan_marks_trialing_without_stripe_checkout():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(f"{tmpdir}/billing-free.db")
        asyncio.run(db.initialize())
        server, stripe = _make_server(db)
        client = TestClient(server.app)

        headers = {"X-API-Key": server._admin_key}
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"tenant_id": "acme", "plan": "free"},
            headers=headers,
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["free"] is True
        assert payload["status"] == "trialing"
        assert payload["plan"] == "free"
        assert not stripe.calls

        tenant = asyncio.run(db.get_tenant("acme"))
        assert tenant is not None
        assert tenant["status"] == "trialing"
        asyncio.run(db.close())


def test_billing_checkout_paid_plan_uses_requested_plan():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(f"{tmpdir}/billing-pro.db")
        asyncio.run(db.initialize())
        server, stripe = _make_server(db)
        client = TestClient(server.app)

        headers = {"X-API-Key": server._admin_key}
        resp = client.post(
            "/api/v1/billing/checkout",
            json={
                "tenant_id": "acme",
                "plan": "pro",
                "success_url": "https://app.example/success",
                "cancel_url": "https://app.example/cancel",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert stripe.calls
        assert stripe.calls[0]["plan"] == "pro"
        asyncio.run(db.close())


def test_billing_checkout_rejects_unconfigured_paid_plan():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(f"{tmpdir}/billing-premium.db")
        asyncio.run(db.initialize())
        server, _stripe = _make_server(db)
        client = TestClient(server.app)

        headers = {"X-API-Key": server._admin_key}
        resp = client.post(
            "/api/v1/billing/checkout",
            json={
                "tenant_id": "acme",
                "plan": "premium",
                "success_url": "https://app.example/success",
                "cancel_url": "https://app.example/cancel",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]
        asyncio.run(db.close())
