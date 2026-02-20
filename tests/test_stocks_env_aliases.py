from src.core.config import load_config_with_overrides


def test_alpaca_alias_env_vars_are_supported(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY", "alias-key")
    monkeypatch.setenv("ALPACA_SECRET", "alias-secret")
    monkeypatch.setenv("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets/v2")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

    cfg = load_config_with_overrides()

    assert cfg.stocks.alpaca_api_key == "alias-key"
    assert cfg.stocks.alpaca_api_secret == "alias-secret"
    assert cfg.stocks.alpaca_base_url == "https://paper-api.alpaca.markets"


def test_alpaca_canonical_env_vars_override_aliases(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY", "alias-key")
    monkeypatch.setenv("ALPACA_SECRET", "alias-secret")
    monkeypatch.setenv("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets/v2")
    monkeypatch.setenv("ALPACA_API_KEY", "canonical-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "canonical-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    cfg = load_config_with_overrides()

    assert cfg.stocks.alpaca_api_key == "canonical-key"
    assert cfg.stocks.alpaca_api_secret == "canonical-secret"
    assert cfg.stocks.alpaca_base_url == "https://paper-api.alpaca.markets"
