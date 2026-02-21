from src.core.config import load_config_with_overrides


def test_stripe_env_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("BILLING_STRIPE_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_123")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_123")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro_123")
    monkeypatch.setenv("STRIPE_PRICE_ID_PREMIUM", "price_premium_123")
    monkeypatch.setenv("STRIPE_CURRENCY", "usd")

    cfg = load_config_with_overrides()

    assert cfg.billing.stripe.enabled is True
    assert cfg.billing.stripe.secret_key == "sk_test_123"
    assert cfg.billing.stripe.webhook_secret == "whsec_123"
    assert cfg.billing.stripe.price_id == "price_123"
    assert cfg.billing.stripe.price_id_pro == "price_pro_123"
    assert cfg.billing.stripe.price_id_premium == "price_premium_123"
    assert cfg.billing.stripe.currency == "usd"
