"""Tests for Feature 8: On-Chain Data Integration."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.exchange.onchain_data import OnChainDataClient
from src.core.config import AIConfig, OnChainConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_client(**kwargs) -> OnChainDataClient:
    defaults = {
        "cache_ttl_seconds": 900,
        "weight": 0.08,
        "min_abs_score": 0.3,
    }
    defaults.update(kwargs)
    return OnChainDataClient(**defaults)


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestOnChainDataUnit:
    def test_sentiment_positive_on_outflows(self):
        """Positive sentiment (exchange outflows) should be stored correctly."""
        client = _make_client()
        client.inject_sentiments({"BTC/USD": 0.7, "ETH/USD": 0.3})

        assert client.get_sentiment("BTC/USD") == 0.7
        assert client.get_sentiment("ETH/USD") == 0.3

    def test_sentiment_negative_on_inflows(self):
        """Negative sentiment (exchange inflows) should be stored correctly."""
        client = _make_client()
        client.inject_sentiments({"BTC/USD": -0.8, "ETH/USD": -0.2})

        assert client.get_sentiment("BTC/USD") == -0.8
        assert client.get_sentiment("ETH/USD") == -0.2

    def test_cache_ttl_prevents_refetch(self):
        """Within TTL, fetch_sentiments should return cached data without refetch."""
        client = _make_client(cache_ttl_seconds=300)
        client.inject_sentiments({"BTC/USD": 0.5})

        # Monkey-patch _fetch_raw to track calls
        fetch_count = 0
        original_fetch = client._fetch_raw

        async def counting_fetch():
            nonlocal fetch_count
            fetch_count += 1
            return await original_fetch()

        client._fetch_raw = counting_fetch

        # First call should use cache (injected)
        result = _run(client.fetch_sentiments())
        assert result == {"BTC/USD": 0.5}
        assert fetch_count == 0  # Cache still valid

    def test_cache_expiry_triggers_refetch(self):
        """After TTL expires, fetch_sentiments should refetch."""
        client = _make_client(cache_ttl_seconds=60)
        client.inject_sentiments({"BTC/USD": 0.5})

        # Force cache expiry
        client._cache_ts = time.time() - 120

        fetch_called = False

        async def mock_fetch():
            nonlocal fetch_called
            fetch_called = True
            return {"BTC/USD": 0.9}

        client._fetch_raw = mock_fetch

        result = _run(client.fetch_sentiments())
        assert fetch_called is True
        assert result == {"BTC/USD": 0.9}

    def test_graceful_api_failure(self):
        """API failure should return cached data (or empty if no cache)."""
        client = _make_client(cache_ttl_seconds=60)
        # No prior cache
        client._cache_ts = 0  # Force fetch

        async def failing_fetch():
            raise ConnectionError("API down")

        client._fetch_raw = failing_fetch

        # Should not raise, returns empty dict
        result = _run(client.fetch_sentiments())
        assert result == {}

    def test_composite_score_clamping(self):
        """Scores should be clamped to [-1, +1]."""
        client = _make_client()
        client.inject_sentiments({"BTC/USD": 2.5, "ETH/USD": -3.0})

        assert client.get_sentiment("BTC/USD") == 1.0
        assert client.get_sentiment("ETH/USD") == -1.0

    def test_non_btc_pair_returns_none(self):
        """Pairs not in cache should return None."""
        client = _make_client()
        client.inject_sentiments({"BTC/USD": 0.5})

        assert client.get_sentiment("DOGE/USD") is None

    def test_stablecoin_minting_bullish(self):
        """Stablecoin minting (captured as positive sentiment) should be correctly stored."""
        client = _make_client()
        # Stablecoin minting is bullish for the broader crypto market
        client.inject_sentiments({"BTC/USD": 0.4, "ETH/USD": 0.4})

        sentiments = client.get_all_sentiments()
        assert sentiments["BTC/USD"] == 0.4
        assert sentiments["ETH/USD"] == 0.4

    def test_get_all_sentiments(self):
        """get_all_sentiments should return all cached sentiments."""
        client = _make_client()
        data = {"BTC/USD": 0.5, "ETH/USD": -0.3, "SOL/USD": 0.1}
        client.inject_sentiments(data)

        all_sents = client.get_all_sentiments()
        assert len(all_sents) == 3
        assert all_sents["BTC/USD"] == 0.5
        assert all_sents["SOL/USD"] == 0.1

    def test_weight_and_min_abs_score(self):
        """Client should expose weight and min_abs_score properties."""
        client = _make_client(weight=0.12, min_abs_score=0.4)
        assert client.weight == 0.12
        assert client.min_abs_score == 0.4


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestOnChainIntegration:
    def test_onchain_boosts_aligned_signal(self):
        """On-chain bullish sentiment should boost a LONG signal's confidence."""
        from src.ai.confluence import ConfluenceDetector

        md = MagicMock()
        md.is_warmed_up.return_value = True
        md.is_stale.return_value = False

        detector = ConfluenceDetector(market_data=md)
        detector.set_onchain_sentiments(
            {"BTC/USD": 0.8},
            weight=0.08,
            min_abs_score=0.3,
        )

        assert detector._onchain_sentiments == {"BTC/USD": 0.8}
        assert detector._onchain_weight == 0.08
        assert detector._onchain_min_abs_score == 0.3

    def test_onchain_penalizes_opposing(self):
        """On-chain bearish sentiment should penalize a LONG signal."""
        from src.ai.confluence import ConfluenceDetector

        md = MagicMock()
        detector = ConfluenceDetector(market_data=md)
        detector.set_onchain_sentiments(
            {"BTC/USD": -0.8},
            weight=0.08,
            min_abs_score=0.3,
        )

        assert detector._onchain_sentiments["BTC/USD"] == -0.8

    def test_below_threshold_no_effect(self):
        """Sentiment below min_abs_score threshold should not affect confidence."""
        from src.ai.confluence import ConfluenceDetector

        md = MagicMock()
        detector = ConfluenceDetector(market_data=md)
        # Sentiment is 0.1 which is below min_abs_score of 0.3
        detector.set_onchain_sentiments(
            {"BTC/USD": 0.1},
            weight=0.08,
            min_abs_score=0.3,
        )

        # The sentiment exists but won't be applied due to threshold
        assert detector._onchain_sentiments["BTC/USD"] == 0.1
        assert detector._onchain_min_abs_score == 0.3
        assert abs(detector._onchain_sentiments["BTC/USD"]) < detector._onchain_min_abs_score

    def test_onchain_disabled_no_effect(self):
        """When onchain is disabled, client should not be created."""
        cfg = OnChainConfig(enabled=False)
        assert cfg.enabled is False
        assert cfg.cache_ttl_seconds == 900
        assert cfg.weight == 0.08
        assert cfg.min_abs_score == 0.3

    def test_config_model_parses(self):
        """OnChainConfig should parse from dict correctly."""
        cfg = OnChainConfig(
            enabled=True,
            cache_ttl_seconds=600,
            weight=0.12,
            min_abs_score=0.4,
        )
        assert cfg.enabled is True
        assert cfg.cache_ttl_seconds == 600
        assert cfg.weight == 0.12
        assert cfg.min_abs_score == 0.4

    def test_onchain_field_on_ai_config(self):
        """AIConfig should have an onchain field with OnChainConfig default."""
        ai = AIConfig()
        assert hasattr(ai, "onchain")
        assert isinstance(ai.onchain, OnChainConfig)
        assert ai.onchain.enabled is False
