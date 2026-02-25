from src.core.config import load_config_with_overrides


def test_alpaca_alias_env_vars_are_supported(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY", "alias-key")
    monkeypatch.setenv("ALPACA_SECRET", "alias-secret")
    monkeypatch.setenv("ALPACA_ENDPOINT", "[REDACTED]")
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_API_SECRET", "")
    monkeypatch.setenv("ALPACA_BASE_URL", "")

    cfg = load_config_with_overrides()

    assert cfg.stocks.alpaca_api_key == "alias-key"
    assert cfg.stocks.alpaca_api_secret == "alias-secret"
    assert cfg.stocks.alpaca_base_url == "[REDACTED]"


def test_alpaca_canonical_env_vars_override_aliases(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY", "alias-key")
    monkeypatch.setenv("ALPACA_SECRET", "alias-secret")
    monkeypatch.setenv("ALPACA_ENDPOINT", "[REDACTED]")
    monkeypatch.setenv("ALPACA_API_KEY", "canonical-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "canonical-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "[REDACTED]")

    cfg = load_config_with_overrides()

    assert cfg.stocks.alpaca_api_key == "canonical-key"
    assert cfg.stocks.alpaca_api_secret == "canonical-secret"
    assert cfg.stocks.alpaca_base_url == "[REDACTED]"
