"""
Elasticsearch connection manager — async bulk indexing with non-blocking enqueue.

Provides a thin wrapper around the ``elasticsearch[async]`` client with:
- Background flush loop that drains a bounded deque of pending documents
- Index template creation for all 5 index types (candles, orderbook, trades, sentiment, onchain)
- Monthly index retention cleanup
- Health-check helper

Design: ``enqueue()`` is **synchronous** so WebSocket handlers can call it
without ``await``, adding zero latency to the hot path.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("es_client")

# ---------------------------------------------------------------------------
# Index templates / mappings
# ---------------------------------------------------------------------------

INDEX_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "candles": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": {
            "properties": {
                "pair": {"type": "keyword"},
                "timeframe": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "open": {"type": "float"},
                "high": {"type": "float"},
                "low": {"type": "float"},
                "close": {"type": "float"},
                "volume": {"type": "float"},
                "vwap": {"type": "float"},
                # Indicator snapshots
                "rsi": {"type": "float"},
                "ema_fast": {"type": "float"},
                "ema_slow": {"type": "float"},
                "atr": {"type": "float"},
                "atr_pct": {"type": "float"},
                "adx": {"type": "float"},
                "bb_upper": {"type": "float"},
                "bb_lower": {"type": "float"},
                "volume_ratio": {"type": "float"},
                "trend_strength": {"type": "float"},
            }
        },
    },
    "orderbook": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": {
            "properties": {
                "pair": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "obi": {"type": "float"},
                "spread_pct": {"type": "float"},
                "book_score": {"type": "float"},
                "bid_volume": {"type": "float"},
                "ask_volume": {"type": "float"},
                "whale_bias": {"type": "float"},
                "mid_price": {"type": "float"},
            }
        },
    },
    "sentiment": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": {
            "properties": {
                "source": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "fear_greed_value": {"type": "integer"},
                "fear_greed_label": {"type": "keyword"},
                "news_title": {"type": "text"},
                "news_sentiment": {"type": "keyword"},
                "news_pair": {"type": "keyword"},
            }
        },
    },
    "onchain": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": {
            "properties": {
                "source": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "mempool_tx_count": {"type": "integer"},
                "mempool_vsize": {"type": "long"},
                "fee_fastest": {"type": "float"},
                "fee_half_hour": {"type": "float"},
                "fee_hour": {"type": "float"},
                "hashrate": {"type": "float"},
            }
        },
    },
    "market": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": {
            "properties": {
                "coin_id": {"type": "keyword"},
                "pair": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "market_cap": {"type": "long"},
                "market_cap_rank": {"type": "integer"},
                "total_volume_24h": {"type": "float"},
                "price_change_24h_pct": {"type": "float"},
            }
        },
    },
    "trades": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "10s",
        },
        "mappings": {
            "properties": {
                "event": {"type": "keyword"},  # opened | closed
                "timestamp": {"type": "date", "format": "epoch_second"},
                "canonical_source": {"type": "keyword"},
                "analytics_mirror": {"type": "boolean"},
                "trade_id": {"type": "keyword"},
                "tenant_id": {"type": "keyword"},
                "pair": {"type": "keyword"},
                "side": {"type": "keyword"},
                "strategy": {"type": "keyword"},
                "mode": {"type": "keyword"},
                "status": {"type": "keyword"},
                "reason": {"type": "keyword"},
                "entry_price": {"type": "float"},
                "exit_price": {"type": "float"},
                "quantity": {"type": "float"},
                "size_usd": {"type": "float"},
                "stop_loss": {"type": "float"},
                "take_profit": {"type": "float"},
                "confidence": {"type": "float"},
                "pnl": {"type": "float"},
                "pnl_pct": {"type": "float"},
                "fees": {"type": "float"},
            }
        },
    },
}

# Retention policy: index_type -> days to keep
DEFAULT_RETENTION: Dict[str, int] = {
    "candles": 90,
    "orderbook": 30,
    "sentiment": 180,
    "onchain": 180,
    "market": 180,
    "trades": 365,
}

# Persistence contract: SQL ledger is canonical, ES is analytics mirror.
LEDGER_MIRROR_DOC_TYPES = {"trades", "positions", "backtest_runs"}


class ESClient:
    """Async Elasticsearch connection with non-blocking bulk buffer."""

    def __init__(
        self,
        hosts: List[str],
        index_prefix: str = "novapulse",
        bulk_size: int = 500,
        flush_interval: float = 10.0,
        buffer_maxlen: int = 10_000,
        retention_days: Optional[Dict[str, int]] = None,
        api_key: str = "",
        cloud_id: str = "",
    ):
        self.hosts = hosts
        self.index_prefix = index_prefix
        self.bulk_size = bulk_size
        self.flush_interval = flush_interval
        self.retention_days = retention_days or dict(DEFAULT_RETENTION)
        self.api_key = api_key
        self.cloud_id = cloud_id

        self._buffer_maxlen = max(1, int(buffer_maxlen or 1))
        self._buffer: deque = deque(maxlen=self._buffer_maxlen)
        self._es = None  # AsyncElasticsearch instance
        self._flush_task: Optional[asyncio.Task] = None
        self._closed = False
        self._serverless = False
        self._dropped_docs = 0
        self._last_drop_log_ts = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establish connection and create index templates."""
        try:
            from elasticsearch import AsyncElasticsearch

            kwargs: Dict[str, Any] = {
                "request_timeout": 30,
                "max_retries": 3,
                "retry_on_timeout": True,
            }

            # Elastic Cloud or self-hosted with API key auth
            if self.cloud_id:
                kwargs["cloud_id"] = self.cloud_id
            else:
                kwargs["hosts"] = self.hosts

            if self.api_key:
                kwargs["api_key"] = self.api_key

            self._es = AsyncElasticsearch(**kwargs)
            info = await self._es.info()
            version = info.get("version", {}).get("number", "unknown")
            # Detect serverless mode (Elastic Cloud Serverless)
            build_flavor = info.get("version", {}).get("build_flavor", "")
            self._serverless = build_flavor == "serverless"
            logger.info(
                "Elasticsearch connected",
                version=version,
                hosts=self.hosts,
                serverless=self._serverless,
            )

            await self._create_index_templates()

            # Start background flush loop
            self._flush_task = asyncio.create_task(self._flush_loop())
            return True
        except Exception as e:
            logger.error("Elasticsearch connection failed", error=repr(e))
            self._es = None
            return False

    async def close(self) -> None:
        """Flush remaining buffer and close connection."""
        self._closed = True
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
        # Final flush
        if self._es and self._buffer:
            try:
                await self._flush_buffer()
            except Exception:
                pass
        if self._es:
            try:
                await self._es.close()
            except Exception:
                pass
        self._es = None
        logger.info(
            "Elasticsearch client closed",
            dropped_docs=self._dropped_docs,
            queue_depth=len(self._buffer),
        )

    async def health_check(self) -> bool:
        """Return True if ES is reachable."""
        if not self._es:
            return False
        try:
            # _cluster/health is unavailable on Elastic Cloud Serverless;
            # fall back to a simple info() ping.
            resp = await self._es.cluster.health(timeout="5s")
            return resp.get("status") in ("green", "yellow")
        except Exception:
            try:
                await self._es.info()
                return True
            except Exception:
                return False

    @property
    def connected(self) -> bool:
        return self._es is not None

    @property
    def queue_depth(self) -> int:
        return len(self._buffer)

    @property
    def queue_capacity(self) -> int:
        return self._buffer_maxlen

    @property
    def dropped_docs(self) -> int:
        return self._dropped_docs

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_name(self, doc_type: str, ts: Optional[float] = None) -> str:
        """Monthly index name: ``novapulse-candles-2026.02``."""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
        return f"{self.index_prefix}-{doc_type}-{dt.strftime('%Y.%m')}"

    def enqueue(
        self,
        doc_type: str,
        doc: Dict[str, Any],
        doc_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """
        Add a document to the bulk buffer (synchronous, non-blocking).

        This is the main entry point for WS handlers — no ``await`` needed.
        """
        if self._closed or self._es is None:
            return
        action: Dict[str, Any] = {
            "_index": self.index_name(doc_type, timestamp),
            "_source": doc,
        }
        if doc_id:
            action["_id"] = doc_id
        was_full = len(self._buffer) >= self._buffer_maxlen
        self._buffer.append(action)
        if was_full:
            self._dropped_docs += 1
            now_ts = time.time()
            should_log = (
                self._dropped_docs == 1
                or self._dropped_docs % 100 == 0
                or (now_ts - self._last_drop_log_ts) >= 60.0
            )
            if should_log:
                self._last_drop_log_ts = now_ts
                logger.warning(
                    "ES queue overflow: dropping oldest buffered docs",
                    dropped_docs=self._dropped_docs,
                    queue_depth=len(self._buffer),
                    queue_capacity=self._buffer_maxlen,
                )
        # Self-heal: restart flush loop if it was cancelled unexpectedly
        if self._flush_task is None or self._flush_task.done():
            try:
                self._flush_task = asyncio.get_running_loop().create_task(self._flush_loop())
                logger.info("ES flush loop restarted (self-heal)")
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Background flush
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Periodically flush the bulk buffer to ES."""
        logger.info("ES flush loop started", interval=self.flush_interval)
        while not self._closed:
            try:
                await asyncio.sleep(self.flush_interval)
                if self._buffer:
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("ES flush error", error=repr(e))

    async def _flush_buffer(self) -> None:
        """Drain current buffer into a bulk request."""
        if not self._es or not self._buffer:
            return

        # Snapshot and clear in one pass
        batch: List[Dict[str, Any]] = []
        while self._buffer and len(batch) < self.bulk_size * 2:
            batch.append(self._buffer.popleft())

        if not batch:
            return

        try:
            from elasticsearch.helpers import async_bulk

            actions = batch
            success, errors = await async_bulk(
                self._es,
                actions,
                raise_on_error=False,
                stats_only=True,
            )
            if errors:
                logger.warning("ES bulk indexing errors", success=success, errors=errors)
            else:
                logger.debug("ES bulk flush", docs=success)
        except Exception as e:
            logger.warning("ES bulk flush failed", error=repr(e), batch_size=len(batch))

    # ------------------------------------------------------------------
    # Index templates
    # ------------------------------------------------------------------

    async def _create_index_templates(self) -> None:
        """Create/update index templates for all document types."""
        if not self._es:
            return
        # Settings unavailable on Elastic Cloud Serverless
        _SERVERLESS_SKIP_SETTINGS = {"number_of_shards", "number_of_replicas"}

        for doc_type, template in INDEX_TEMPLATES.items():
            template_name = f"{self.index_prefix}-{doc_type}"
            settings = dict(template["settings"])
            if self._serverless:
                for key in _SERVERLESS_SKIP_SETTINGS:
                    settings.pop(key, None)
            body = {
                "index_patterns": [f"{self.index_prefix}-{doc_type}-*"],
                "template": {
                    "settings": settings,
                    "mappings": template["mappings"],
                },
                "priority": 100,
            }
            try:
                await self._es.indices.put_index_template(
                    name=template_name,
                    body=body,
                )
                logger.debug("Index template created", template=template_name)
            except Exception as e:
                logger.warning("Failed to create index template", template=template_name, error=repr(e))

    # ------------------------------------------------------------------
    # Retention cleanup
    # ------------------------------------------------------------------

    async def cleanup_old_indices(self) -> int:
        """Delete indices older than configured retention. Returns count deleted."""
        if not self._es:
            return 0

        deleted = 0
        now = datetime.now(timezone.utc)

        for doc_type, max_days in self.retention_days.items():
            pattern = f"{self.index_prefix}-{doc_type}-*"
            try:
                resp = await self._es.indices.get(index=pattern, ignore_unavailable=True)
                indices = list(resp.keys()) if isinstance(resp, dict) else []
            except Exception:
                indices = []

            for idx_name in indices:
                # Extract YYYY.MM from index name
                suffix = idx_name.rsplit("-", 1)[-1]
                try:
                    idx_date = datetime.strptime(suffix, "%Y.%m").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                age_days = (now - idx_date).days
                if age_days > max_days:
                    try:
                        await self._es.indices.delete(index=idx_name)
                        logger.info("Deleted old ES index", index=idx_name, age_days=age_days)
                        deleted += 1
                    except Exception as e:
                        logger.warning("Failed to delete old index", index=idx_name, error=repr(e))

        return deleted

    # ------------------------------------------------------------------
    # Query helpers (used by training_data)
    # ------------------------------------------------------------------

    async def search(
        self,
        doc_type: str,
        body: Dict[str, Any],
        size: int = 1,
    ) -> List[Dict[str, Any]]:
        """Run an ES search and return list of _source dicts."""
        if not self._es:
            return []
        if doc_type in LEDGER_MIRROR_DOC_TYPES:
            logger.warning(
                "Blocked ES search for canonical ledger data",
                doc_type=doc_type,
                canonical_store="sqlite",
            )
            return []
        pattern = f"{self.index_prefix}-{doc_type}-*"
        try:
            resp = await self._es.search(index=pattern, body=body, size=size)
            return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]
        except Exception as e:
            logger.debug("ES search error", doc_type=doc_type, error=repr(e))
            return []

    async def get_latest(self, doc_type: str, filter_term: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Get most recent document of a type, optionally filtered."""
        must = []
        if filter_term:
            for k, v in filter_term.items():
                must.append({"term": {k: v}})
        body: Dict[str, Any] = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "sort": [{"timestamp": {"order": "desc"}}],
        }
        results = await self.search(doc_type, body, size=1)
        return results[0] if results else None

    async def get_nearest(
        self,
        doc_type: str,
        timestamp: float,
        window_seconds: int = 300,
        filter_term: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get document closest to a timestamp within a window.

        Queries two ranges (before and after the target) and picks the
        doc with the smallest absolute time delta.  This avoids
        ``_script`` sorts which are unavailable on Elastic Cloud Serverless.
        """
        must_base: list = [
            {
                "range": {
                    "timestamp": {
                        "gte": int(timestamp - window_seconds),
                        "lte": int(timestamp + window_seconds),
                        "format": "epoch_second",
                    }
                }
            }
        ]
        if filter_term:
            for k, v in filter_term.items():
                must_base.append({"term": {k: v}})

        # Fetch closest before and closest after, then pick nearest
        candidates: List[Dict[str, Any]] = []
        for order in ("desc", "asc"):
            body = {
                "query": {"bool": {"must": must_base}},
                "sort": [{"timestamp": {"order": order}}],
            }
            hits = await self.search(doc_type, body, size=1)
            candidates.extend(hits)

        if not candidates:
            return None
        # Pick the one with smallest time delta
        target = int(timestamp)
        return min(candidates, key=lambda d: abs(int(d.get("timestamp", 0)) - target))
