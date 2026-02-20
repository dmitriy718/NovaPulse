"""
Data ingestion — hooks into WS handlers and polls external APIs.

Two main classes:

1. ``MarketDataIndexer`` — called from engine WS handlers to index
   candles and order book snapshots into Elasticsearch.

2. ``ExternalDataCollector`` — background polling loops for external
   data sources (Fear & Greed, CoinGecko, CryptoPanic, mempool.space).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.logger import get_logger
from src.data.es_client import ESClient

logger = get_logger("es_ingestion")

# Pair -> CoinGecko ID mapping for the standard trading list
_PAIR_TO_COINGECKO: Dict[str, str] = {
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "SOL/USD": "solana",
    "XRP/USD": "ripple",
    "ADA/USD": "cardano",
    "DOT/USD": "polkadot",
    "AVAX/USD": "avalanche-2",
    "LINK/USD": "chainlink",
}


# ======================================================================
# MarketDataIndexer — WS handler hooks
# ======================================================================

class MarketDataIndexer:
    """Index market data from existing WS handlers into ES.

    Both ``index_candle`` and ``index_orderbook`` are designed to be
    called **inline** from the WS handler — they call ``es.enqueue()``
    which is synchronous and non-blocking.
    """

    def __init__(self, es: ESClient, market_data: Any):
        self.es = es
        self.market_data = market_data
        # Throttle: last orderbook index time per pair
        self._last_book_index: Dict[str, float] = {}
        self._book_throttle_seconds = 30.0

    def index_candle(self, pair: str, bar: Dict[str, Any]) -> None:
        """Index a closed candle with indicator snapshots.

        Called from ``_handle_ohlc()`` when ``is_new_bar`` is True.
        """
        try:
            ts = float(bar.get("time", time.time()))

            # Compute indicator snapshots from the market_data cache
            indicators = self._compute_indicators(pair)

            doc = {
                "pair": pair,
                "timeframe": "1m",
                "timestamp": int(ts),
                "open": float(bar.get("open", 0)),
                "high": float(bar.get("high", 0)),
                "low": float(bar.get("low", 0)),
                "close": float(bar.get("close", 0)),
                "volume": float(bar.get("volume", 0)),
                "vwap": float(bar.get("vwap", 0)),
                **indicators,
            }
            doc_id = f"{pair}:1m:{int(ts)}"
            self.es.enqueue("candles", doc, doc_id=doc_id, timestamp=ts)
        except Exception as e:
            logger.debug("index_candle error", pair=pair, error=repr(e))

    def _compute_indicators(self, pair: str) -> Dict[str, float]:
        """Compute indicator values from cached bars."""
        try:
            from src.utils.indicators import (
                atr as compute_atr,
                atr_percent,
                adx as compute_adx,
                bollinger_bands,
                ema,
                rsi as compute_rsi,
                trend_strength as compute_trend_strength,
                volume_ratio as compute_volume_ratio,
            )

            closes = self.market_data.get_closes(pair)
            if closes is None or len(closes) < 30:
                return {}

            highs = self.market_data.get_highs(pair)
            lows = self.market_data.get_lows(pair)
            volumes = self.market_data.get_volumes(pair)

            rsi_vals = compute_rsi(closes, 14)
            ema_f = ema(closes, 20)
            ema_s = ema(closes, 50)
            atr_vals = compute_atr(highs, lows, closes, 14)
            atr_pct_vals = atr_percent(highs, lows, closes, 14)
            adx_vals = compute_adx(highs, lows, closes, 14)
            bb_upper, _bb_mid, bb_lower = bollinger_bands(closes, 20, 2.0)
            vol_ratio = compute_volume_ratio(volumes, 20)
            ts_vals = compute_trend_strength(closes, 5, 13)

            def _last_valid(arr: np.ndarray) -> float:
                for i in range(len(arr) - 1, -1, -1):
                    v = arr[i]
                    if not np.isnan(v):
                        return float(v)
                return 0.0

            return {
                "rsi": _last_valid(rsi_vals),
                "ema_fast": _last_valid(ema_f),
                "ema_slow": _last_valid(ema_s),
                "atr": _last_valid(atr_vals),
                "atr_pct": _last_valid(atr_pct_vals),
                "adx": _last_valid(adx_vals),
                "bb_upper": _last_valid(bb_upper),
                "bb_lower": _last_valid(bb_lower),
                "volume_ratio": _last_valid(vol_ratio),
                "trend_strength": _last_valid(ts_vals),
            }
        except Exception as e:
            logger.debug("_compute_indicators error", pair=pair, error=repr(e))
            return {}

    def index_orderbook(self, pair: str, analysis: Dict[str, Any]) -> None:
        """Index order book analysis snapshot, throttled to 1 doc/30s per pair.

        Called from ``_handle_book()`` after ``OrderBookAnalyzer.analyze()``.
        """
        now = time.time()
        last = self._last_book_index.get(pair, 0.0)
        if now - last < self._book_throttle_seconds:
            return

        try:
            self._last_book_index[pair] = now
            doc = {
                "pair": pair,
                "timestamp": int(now),
                "obi": float(analysis.get("obi", 0)),
                "spread_pct": float(analysis.get("spread_pct", 0)),
                "book_score": float(analysis.get("book_score", 0)),
                "bid_volume": float(analysis.get("bid_volume", 0)),
                "ask_volume": float(analysis.get("ask_volume", 0)),
                "whale_bias": float(analysis.get("whale_bias", 0)),
                "mid_price": float(analysis.get("mid_price", 0)),
            }
            self.es.enqueue("orderbook", doc, timestamp=now)
        except Exception as e:
            logger.debug("index_orderbook error", pair=pair, error=repr(e))


# ======================================================================
# ExternalDataCollector — background polling loops
# ======================================================================

class ExternalDataCollector:
    """Polls external APIs and indexes data into ES."""

    def __init__(
        self,
        es: ESClient,
        pairs: List[str],
        coingecko_api_key: str = "",
        cryptopanic_api_key: str = "",
        fear_greed_interval: int = 3600,
        coingecko_interval: int = 600,
        cryptopanic_interval: int = 600,
        onchain_interval: int = 3600,
    ):
        self.es = es
        self.pairs = pairs
        self.coingecko_api_key = coingecko_api_key
        self.cryptopanic_api_key = cryptopanic_api_key
        self.fear_greed_interval = fear_greed_interval
        self.coingecko_interval = coingecko_interval
        self.cryptopanic_interval = cryptopanic_interval
        self.onchain_interval = onchain_interval

    # ------------------------------------------------------------------
    # Fear & Greed Index (alternative.me — no key needed)
    # ------------------------------------------------------------------

    async def poll_fear_greed(self) -> None:
        """Poll Fear & Greed index in a loop."""
        import httpx

        logger.info("Fear & Greed polling started", interval=self.fear_greed_interval)
        while True:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get("https://api.alternative.me/fng/?limit=1&format=json")
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("data", [])
                    if items:
                        item = items[0]
                        now = time.time()
                        doc = {
                            "source": "fear_greed",
                            "timestamp": int(now),
                            "fear_greed_value": int(item.get("value", 0)),
                            "fear_greed_label": str(item.get("value_classification", "")),
                        }
                        self.es.enqueue("sentiment", doc, timestamp=now)
                        logger.debug("Fear & Greed indexed", value=doc["fear_greed_value"])
            except Exception as e:
                logger.debug("Fear & Greed poll error", error=repr(e))
            await asyncio.sleep(self.fear_greed_interval)

    # ------------------------------------------------------------------
    # CoinGecko market data (free tier, optional demo key)
    # ------------------------------------------------------------------

    async def poll_coingecko(self) -> None:
        """Poll CoinGecko market data in a loop."""
        import httpx

        logger.info("CoinGecko polling started", interval=self.coingecko_interval)
        coin_ids = [
            _PAIR_TO_COINGECKO[p]
            for p in self.pairs
            if p in _PAIR_TO_COINGECKO
        ]
        if not coin_ids:
            logger.warning("No CoinGecko IDs mapped for configured pairs")
            return

        ids_str = ",".join(coin_ids)
        base_url = "https://api.coingecko.com/api/v3/coins/markets"
        headers: Dict[str, str] = {}
        if self.coingecko_api_key:
            headers["x-cg-demo-key"] = self.coingecko_api_key

        while True:
            try:
                params = {
                    "vs_currency": "usd",
                    "ids": ids_str,
                    "order": "market_cap_desc",
                    "sparkline": "false",
                }
                async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                    resp = await client.get(base_url, params=params)
                    resp.raise_for_status()
                    coins = resp.json()

                now = time.time()
                # Reverse map: coingecko_id -> pair
                id_to_pair = {v: k for k, v in _PAIR_TO_COINGECKO.items()}

                for coin in coins:
                    cid = coin.get("id", "")
                    pair = id_to_pair.get(cid, "")
                    doc = {
                        "coin_id": cid,
                        "pair": pair,
                        "timestamp": int(now),
                        "market_cap": int(coin.get("market_cap", 0) or 0),
                        "market_cap_rank": int(coin.get("market_cap_rank", 0) or 0),
                        "total_volume_24h": float(coin.get("total_volume", 0) or 0),
                        "price_change_24h_pct": float(coin.get("price_change_percentage_24h", 0) or 0),
                    }
                    self.es.enqueue("market", doc, timestamp=now)
                logger.debug("CoinGecko indexed", coins=len(coins))
            except Exception as e:
                logger.debug("CoinGecko poll error", error=repr(e))
            await asyncio.sleep(self.coingecko_interval)

    # ------------------------------------------------------------------
    # CryptoPanic news + sentiment (free tier, requires API key)
    # ------------------------------------------------------------------

    async def poll_cryptopanic(self) -> None:
        """Poll CryptoPanic for news headlines + sentiment."""
        import httpx

        if not self.cryptopanic_api_key:
            logger.info("CryptoPanic API key not configured, skipping news polling")
            return

        logger.info("CryptoPanic polling started", interval=self.cryptopanic_interval)
        base_url = "https://cryptopanic.com/api/v1/posts/"
        seen_ids: set = set()

        while True:
            try:
                params = {
                    "auth_token": self.cryptopanic_api_key,
                    "filter": "important",
                    "public": "true",
                }
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(base_url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                now = time.time()
                results = data.get("results", [])
                new_count = 0
                for post in results[:20]:
                    post_id = str(post.get("id", ""))
                    if post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)
                    new_count += 1

                    # Map sentiment votes to a label
                    votes = post.get("votes", {})
                    pos = int(votes.get("positive", 0) or 0)
                    neg = int(votes.get("negative", 0) or 0)
                    if pos > neg:
                        sentiment = "positive"
                    elif neg > pos:
                        sentiment = "negative"
                    else:
                        sentiment = "neutral"

                    # Try to match a pair from currencies
                    currencies = post.get("currencies", [])
                    pair = ""
                    for cur in (currencies or []):
                        code = (cur.get("code", "") or "").upper()
                        candidate = f"{code}/USD"
                        if candidate in _PAIR_TO_COINGECKO:
                            pair = candidate
                            break

                    doc = {
                        "source": "cryptopanic",
                        "timestamp": int(now),
                        "news_title": str(post.get("title", ""))[:500],
                        "news_sentiment": sentiment,
                        "news_pair": pair,
                    }
                    self.es.enqueue("sentiment", doc, timestamp=now)

                # Keep seen_ids bounded
                if len(seen_ids) > 5000:
                    seen_ids = set(list(seen_ids)[-2500:])

                if new_count:
                    logger.debug("CryptoPanic indexed", new_posts=new_count)
            except Exception as e:
                logger.debug("CryptoPanic poll error", error=repr(e))
            await asyncio.sleep(self.cryptopanic_interval)

    # ------------------------------------------------------------------
    # mempool.space on-chain data (no key needed)
    # ------------------------------------------------------------------

    async def poll_onchain(self) -> None:
        """Poll mempool.space for BTC mempool stats and fee estimates."""
        import httpx

        logger.info("On-chain polling started", interval=self.onchain_interval)
        while True:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    now = time.time()

                    # Mempool stats
                    mem_resp = await client.get("https://mempool.space/api/mempool")
                    mem_resp.raise_for_status()
                    mem = mem_resp.json()

                    # Fee estimates
                    fee_resp = await client.get("https://mempool.space/api/v1/fees/recommended")
                    fee_resp.raise_for_status()
                    fees = fee_resp.json()

                    doc = {
                        "source": "mempool_space",
                        "timestamp": int(now),
                        "mempool_tx_count": int(mem.get("count", 0) or 0),
                        "mempool_vsize": int(mem.get("vsize", 0) or 0),
                        "fee_fastest": float(fees.get("fastestFee", 0) or 0),
                        "fee_half_hour": float(fees.get("halfHourFee", 0) or 0),
                        "fee_hour": float(fees.get("hourFee", 0) or 0),
                        "hashrate": 0.0,  # mempool.space doesn't expose hashrate in the free API
                    }
                    self.es.enqueue("onchain", doc, timestamp=now)
                    logger.debug("On-chain indexed", tx_count=doc["mempool_tx_count"])
            except Exception as e:
                logger.debug("On-chain poll error", error=repr(e))
            await asyncio.sleep(self.onchain_interval)
