from __future__ import annotations

from types import SimpleNamespace

from src.billing.stripe_service import StripeService


class _FakeStripe:
    def __init__(self):
        self.last_params = None
        self.checkout = SimpleNamespace(
            Session=SimpleNamespace(create=self._create_checkout_session)
        )

    def _create_checkout_session(self, **params):
        self.last_params = params
        return SimpleNamespace(url="https://checkout.stripe.test/cs_123", id="cs_123", customer="cus_123")


def test_stripe_service_uses_pro_and_premium_price_ids():
    svc = StripeService(
        secret_key="sk_test_123",
        webhook_secret="whsec_123",
        price_id_pro="price_pro_123",
        price_id_premium="price_premium_123",
    )
    fake = _FakeStripe()
    svc._api = lambda: fake  # type: ignore[method-assign]

    pro = svc.create_checkout_session(
        tenant_id="tenant-a",
        success_url="https://app.example/success",
        cancel_url="https://app.example/cancel",
        plan="pro",
    )
    assert pro is not None
    assert pro["plan"] == "pro"
    assert pro["price_id"] == "price_pro_123"
    assert fake.last_params["line_items"][0]["price"] == "price_pro_123"

    premium = svc.create_checkout_session(
        tenant_id="tenant-a",
        success_url="https://app.example/success",
        cancel_url="https://app.example/cancel",
        plan="premium",
    )
    assert premium is not None
    assert premium["plan"] == "premium"
    assert premium["price_id"] == "price_premium_123"
    assert fake.last_params["line_items"][0]["price"] == "price_premium_123"


def test_stripe_service_falls_back_legacy_price_to_pro():
    svc = StripeService(
        secret_key="sk_test_123",
        webhook_secret="whsec_123",
        price_id="price_legacy_123",
        price_id_premium="price_premium_123",
    )
    fake = _FakeStripe()
    svc._api = lambda: fake  # type: ignore[method-assign]

    out = svc.create_checkout_session(
        tenant_id="tenant-b",
        success_url="https://app.example/success",
        cancel_url="https://app.example/cancel",
        plan="pro",
    )
    assert out is not None
    assert out["price_id"] == "price_legacy_123"
    assert fake.last_params["line_items"][0]["price"] == "price_legacy_123"


def test_stripe_service_rejects_unconfigured_plan():
    svc = StripeService(
        secret_key="sk_test_123",
        webhook_secret="whsec_123",
        price_id_pro="price_pro_123",
    )
    fake = _FakeStripe()
    svc._api = lambda: fake  # type: ignore[method-assign]

    out = svc.create_checkout_session(
        tenant_id="tenant-c",
        success_url="https://app.example/success",
        cancel_url="https://app.example/cancel",
        plan="premium",
    )
    assert out is None
