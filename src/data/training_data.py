"""
Enriched training data provider — merges ES context into SQLite ML samples.

Queries Elasticsearch for market context surrounding each historical trade
and adds up to 9 new features for the TFLite predictor:

- fear_greed           : Fear & Greed Index value (0-100) at trade time
- volume_24h_change    : CoinGecko 24h volume % change
- market_cap_rank_norm : Normalised market cap rank (1/rank)
- es_obi               : Order book imbalance from ES snapshot
- es_spread_pct        : Bid-ask spread from ES snapshot
- es_book_score        : Microstructure book score from ES snapshot
- btc_mempool_tx_count : BTC mempool transaction count
- btc_fee_fastest      : Fastest-confirm BTC fee (sat/vB)
- news_sentiment_score : Aggregated news sentiment score (-1..+1)

Missing data defaults to 0.0 for graceful degradation during cold start.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.data.es_client import ESClient

logger = get_logger("es_training")

# Features this provider can add
ES_FEATURE_NAMES = [
    "fear_greed",
    "volume_24h_change",
    "market_cap_rank_norm",
    "es_obi",
    "es_spread_pct",
    "es_book_score",
    "btc_mempool_tx_count",
    "btc_fee_fastest",
    "news_sentiment_score",
]


class ESTrainingDataProvider:
    """Enrich SQLite ML samples with ES context features."""

    def __init__(self, es: ESClient, window_seconds: int = 300):
        self.es = es
        self.window_seconds = window_seconds

    async def build_enriched_dataset(
        self,
        base_samples: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge ES context features into base training samples.

        Each sample is expected to have:
        - ``features``: dict of existing feature values
        - ``timestamp`` or ``created_at``: epoch float for time lookup
        - ``pair``: trading pair (e.g. "BTC/USD")

        Returns the same list with ``features`` dicts augmented with
        ES-sourced keys.  Gracefully degrades: if ES is down or data is
        missing, features default to 0.0.
        """
        if not self.es.connected:
            logger.debug("ES not connected, returning base features")
            return base_samples

        enriched = 0
        for sample in base_samples:
            ts = float(sample.get("timestamp") or sample.get("created_at") or 0)
            pair = sample.get("pair", "")
            features = sample.get("features", {})

            if ts <= 0:
                continue

            es_features = await self._get_context_features(pair, ts)
            if es_features:
                features.update(es_features)
                enriched += 1

        if enriched:
            logger.info("ES enrichment complete", enriched=enriched, total=len(base_samples))
        return base_samples

    async def _get_context_features(
        self, pair: str, timestamp: float
    ) -> Dict[str, float]:
        """Query ES for context features at a given timestamp."""
        result: Dict[str, float] = {}
        window = self.window_seconds

        # Fear & Greed (global, not pair-specific)
        try:
            fg = await self.es.get_nearest(
                "sentiment", timestamp, window_seconds=7200,
                filter_term={"source": "fear_greed"},
            )
            if fg:
                result["fear_greed"] = float(fg.get("fear_greed_value", 0))
        except Exception:
            pass

        # CoinGecko market data
        try:
            market = await self.es.get_nearest(
                "market", timestamp, window_seconds=1800,
                filter_term={"pair": pair},
            )
            if market:
                result["volume_24h_change"] = float(market.get("price_change_24h_pct", 0))
                rank = int(market.get("market_cap_rank", 0) or 0)
                result["market_cap_rank_norm"] = 1.0 / rank if rank > 0 else 0.0
        except Exception:
            pass

        # Order book snapshot
        try:
            book = await self.es.get_nearest(
                "orderbook", timestamp, window_seconds=window,
                filter_term={"pair": pair},
            )
            if book:
                result["es_obi"] = float(book.get("obi", 0))
                result["es_spread_pct"] = float(book.get("spread_pct", 0))
                result["es_book_score"] = float(book.get("book_score", 0))
        except Exception:
            pass

        # On-chain (BTC mempool)
        try:
            onchain = await self.es.get_nearest(
                "onchain", timestamp, window_seconds=7200,
                filter_term={"source": "mempool_space"},
            )
            if onchain:
                result["btc_mempool_tx_count"] = float(onchain.get("mempool_tx_count", 0))
                result["btc_fee_fastest"] = float(onchain.get("fee_fastest", 0))
        except Exception:
            pass

        # News sentiment (aggregate recent posts)
        try:
            sentiment = await self._aggregate_news_sentiment(pair, timestamp)
            result["news_sentiment_score"] = sentiment
        except Exception:
            pass

        return result

    async def _aggregate_news_sentiment(
        self, pair: str, timestamp: float, lookback: int = 3600
    ) -> float:
        """Aggregate recent news sentiment into a -1..+1 score."""
        must: list = [
            {"term": {"source": "cryptopanic"}},
            {
                "range": {
                    "timestamp": {
                        "gte": int(timestamp - lookback),
                        "lte": int(timestamp),
                        "format": "epoch_second",
                    }
                }
            },
        ]
        # Optionally filter by pair if we have one
        if pair:
            must.append({
                "bool": {
                    "should": [
                        {"term": {"news_pair": pair}},
                        {"term": {"news_pair": ""}},  # Include general crypto news
                    ],
                    "minimum_should_match": 1,
                }
            })

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"timestamp": {"order": "desc"}}],
        }
        results = await self.es.search("sentiment", body, size=50)
        if not results:
            return 0.0

        score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        scores = [score_map.get(r.get("news_sentiment", "neutral"), 0.0) for r in results]
        return sum(scores) / len(scores) if scores else 0.0
