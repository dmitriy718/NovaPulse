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
        self.calls = 0

    def set_db(self, db):
        self._db = db

    def verify_webhook(self, payload: bytes, signature_header: str) -> bool:
        return bool(signature_header)

    async def handle_webhook_event(self, event):
        self.calls += 1


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


def test_billing_webhook_is_idempotent_by_event_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(f"{tmpdir}/billing.db")
        asyncio.run(db.initialize())
        server, stripe = _make_server(db)
        client = TestClient(server.app)

        payload = {
            "id": "evt_123",
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"tenant_id": "default"}}},
        }
        headers = {"Stripe-Signature": "sig"}

        first = client.post("/api/v1/billing/webhook", json=payload, headers=headers)
        second = client.post("/api/v1/billing/webhook", json=payload, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert stripe.calls == 1
        asyncio.run(db.close())


def test_billing_webhook_is_idempotent_without_event_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(f"{tmpdir}/billing-no-id.db")
        asyncio.run(db.initialize())
        server, stripe = _make_server(db)
        client = TestClient(server.app)

        payload = {
            "type": "invoice.paid",
            "data": {"object": {"subscription": "sub_test"}},
        }
        headers = {"Stripe-Signature": "sig"}

        first = client.post("/api/v1/billing/webhook", json=payload, headers=headers)
        second = client.post("/api/v1/billing/webhook", json=payload, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert stripe.calls == 1
        asyncio.run(db.close())
