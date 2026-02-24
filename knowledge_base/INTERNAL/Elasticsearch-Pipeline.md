# NovaPulse Elasticsearch Pipeline

**Version:** 4.5.0
**Last Updated:** 2026-02-24

---

## Overview

NovaPulse optionally mirrors trading data, market metrics, and external sentiment signals into Elasticsearch for analytics, dashboards, and ML feature enrichment. Elasticsearch is never the source of truth -- SQLite remains the canonical ledger for trades, positions, and system state. The ES layer is a read-optimized analytics mirror that can be rebuilt from scratch at any time.

The pipeline is **disabled by default**. It activates only when either `ELASTICSEARCH_HOSTS` or `ELASTICSEARCH_CLOUD_ID` is set in the environment.

---

## ESClient

**File:** `src/data/es_client.py` (~591 lines)
**Class:** `ESClient`

The core async Elasticsearch client wrapping the official `elasticsearch-py` async transport. All indexing goes through a bulk buffer that flushes in the background, avoiding per-document round-trips.

### Initialization

```python
es = ESClient(config)
await es.start()   # creates indices, starts flush task
await es.stop()    # flushes remaining buffer, closes transport
```

The client reads connection details from the environment:

| Environment Variable | Purpose | Example |
|---------------------|---------|---------|
| `ELASTICSEARCH_HOSTS` | Comma-separated host URLs | `https://es1:9200,https://es2:9200` |
| `ELASTICSEARCH_CLOUD_ID` | Elastic Cloud deployment ID | `my-deploy:dXMtY2Vud...` |
| `ELASTICSEARCH_API_KEY` | API key (preferred auth) | `base64-encoded-key` |
| `ELASTICSEARCH_USERNAME` | Basic auth username | `elastic` |
| `ELASTICSEARCH_PASSWORD` | Basic auth password | `changeme` |

Authentication priority: API key > basic auth > cloud ID with embedded credentials.

### Bulk Buffer

Documents are not indexed immediately. They accumulate in an in-memory buffer and are flushed under two conditions:

1. **Max size reached:** buffer hits `es_bulk_max_size` documents (default: 500)
2. **Flush interval elapsed:** `es_bulk_flush_interval_seconds` timer fires (default: 30s)

The flush runs as a background `asyncio.Task` started in `start()`. On flush, the client calls `helpers.async_bulk()` with the accumulated actions. Failed documents are logged but do not halt the pipeline -- partial failures are tolerated.

```python
async def _flush_buffer(self):
    if not self._buffer:
        return
    actions = list(self._buffer)
    self._buffer.clear()
    success, errors = await helpers.async_bulk(
        self._es, actions, raise_on_error=False
    )
    if errors:
        logger.warning("ES bulk indexed %d docs, %d errors", success, len(errors))
```

### Index Types and Naming

All indices follow the pattern: `novapulse-{type}-{tenant_id}-{date}`

| Index Type | Source | Document Fields |
|-----------|--------|-----------------|
| `trades` | Trade open/close events | trade_id, pair, side, entry/exit price, pnl, strategy, fees, metadata |
| `candles` | OHLCV bar closes | pair, timeframe, open, high, low, close, volume, timestamp |
| `orderbook` | L2 book snapshots | pair, bids (top 10), asks (top 10), spread, mid_price, timestamp |
| `sentiment` | IngestionManager | source (fear_greed / cryptopanic / coingecko), value, raw payload, timestamp |
| `onchain` | IngestionManager | metric_name, chain, value, block_height, timestamp |

Index templates with appropriate mappings (keyword vs float vs date) are created on `start()` if they do not exist. Date fields use epoch millis. Price fields use `scaled_float` with a scaling factor of 100,000,000 for sub-cent precision.

### Config Keys

```yaml
elasticsearch:
  enabled: true                         # master switch (also requires env vars)
  bulk_max_size: 500                    # docs before forced flush
  bulk_flush_interval_seconds: 30       # timer-based flush
  index_prefix: "novapulse"             # prefix for all index names
  candle_indexing: true                 # index every bar close
  orderbook_indexing: false             # high volume -- off by default
  sentiment_indexing: true              # fear/greed, cryptopanic, coingecko
  onchain_indexing: true                # on-chain metrics
  ilm_policy: "novapulse-rollover"     # ILM policy name (optional)
```

---

## IngestionManager

**File:** `src/data/ingestion.py` (~411 lines)
**Class:** `IngestionManager`

Polls external data APIs on configurable intervals and feeds the results into ESClient for indexing. Each data source runs as an independent asyncio task.

### Data Sources

#### Fear & Greed Index

- **API:** `https://api.alternative.me/fng/`
- **Poll interval:** 3600s (1 hour) -- the index updates daily, but the poll is hourly to catch updates promptly
- **Fields indexed:** `value` (0-100 int), `value_classification` (Extreme Fear / Fear / Neutral / Greed / Extreme Greed), `timestamp`
- **No API key required**

#### CoinGecko Market Data

- **API:** `https://api.coingecko.com/api/v3/coins/markets`
- **Poll interval:** 300s (5 minutes)
- **Fields indexed:** `market_cap`, `total_volume`, `price_change_percentage_24h`, `market_cap_rank` for top N coins
- **Rate limit handling:** CoinGecko free tier allows ~10-30 calls/min; the manager backs off on 429s with exponential retry

#### CryptoPanic Sentiment

- **API:** `https://cryptopanic.com/api/v1/posts/`
- **Poll interval:** 600s (10 minutes)
- **Requires:** `CRYPTOPANIC_API_KEY` environment variable
- **Fields indexed:** `title`, `kind` (news/media), `domain`, `votes` (positive/negative/important/liked), `currencies` (affected tickers), `published_at`
- **Sentiment scoring:** positive votes minus negative votes, normalized to [-1.0, 1.0]

#### On-Chain Metrics

- **API:** Configurable provider (Glassnode, CryptoQuant, or custom)
- **Poll interval:** 1800s (30 minutes)
- **Metrics collected:** active addresses, exchange net flows, MVRV ratio, SOPR, hash rate
- **Requires:** `ONCHAIN_API_KEY` environment variable
- **Fields indexed:** `metric_name`, `chain`, `value`, `block_height`, `timestamp`

### Lifecycle

```python
ingestion = IngestionManager(config, es_client)
await ingestion.start()    # launches per-source polling tasks
await ingestion.stop()     # cancels all tasks, awaits clean shutdown
```

Each polling task catches all exceptions internally and logs them. A single source failure does not affect other sources or the main trading engine.

---

## TrainingDataProvider

**File:** `src/data/training_data.py` (~191 lines)
**Class:** `TrainingDataProvider`

Enriches ML training samples with features sourced from Elasticsearch. When the ML trainer builds its feature matrix from `ml_features` in SQLite, the `TrainingDataProvider` optionally appends 9 additional ES-sourced features if ES is available.

### ES-Sourced Features (9 total)

| # | Feature | Source | Description |
|---|---------|--------|-------------|
| 1 | `fear_greed_value` | Fear & Greed | 0-100 normalized to [0, 1] |
| 2 | `fear_greed_direction` | Fear & Greed | 1-day delta (positive = improving sentiment) |
| 3 | `btc_market_cap_rank_delta` | CoinGecko | Change in BTC dominance rank over 24h |
| 4 | `total_market_volume_24h` | CoinGecko | Normalized log of total market volume |
| 5 | `sentiment_score` | CryptoPanic | Aggregate positive-negative score for the traded pair's asset |
| 6 | `news_velocity` | CryptoPanic | Count of news items in last 4 hours (normalized) |
| 7 | `active_addresses_zscore` | On-Chain | Z-score of active addresses vs 30-day mean |
| 8 | `exchange_net_flow` | On-Chain | Net exchange flow (positive = inflow = bearish signal) |
| 9 | `mvrv_ratio` | On-Chain | Market Value to Realized Value ratio |

### Graceful Degradation

If Elasticsearch is unavailable or a specific index has no data, the provider returns `NaN` for those features. The ML trainer's scaler handles NaN by imputing with the column median from the training split. This means:

- ES down: model trains on 12 core features only (NaN columns are imputed)
- ES partially available: available features are used, missing ones imputed
- ES fully available: all 21 features (12 core + 9 ES) are used

```python
provider = TrainingDataProvider(es_client)
enriched = await provider.enrich_features(base_features_df, pair, timestamp)
# enriched has 9 additional columns appended
```

### Query Pattern

The provider queries ES using time-windowed aggregations. For a training sample at time `T`, it fetches:

- Fear & Greed: latest value before `T`
- CoinGecko: 24h rolling aggregation ending at `T`
- CryptoPanic: 4h window ending at `T`
- On-Chain: latest value before `T` + 30-day mean for z-score

All queries use `bool` filters with `range` on the `@timestamp` field and `term` on `tenant_id`.

---

## Operational Notes

### Rebuilding ES from SQLite

If ES indices are lost or corrupted, a backfill script re-indexes from SQLite:

```bash
python scripts/es_backfill.py --db trading_kraken_default.db --types trades,candles
```

This reads all historical records from the DB and bulk-indexes them. It is idempotent -- documents with the same `_id` (derived from trade_id or pair+timestamp) are upserted.

### Index Lifecycle Management

If an ILM policy name is configured (`ilm_policy`), the client attaches it to index templates. Recommended rollover policy:

- Hot phase: 7 days or 50 GB
- Warm phase: 30 days (force merge to 1 segment)
- Delete phase: 90 days

For single-node deployments, ILM is optional. Indices are date-stamped, so manual cleanup is straightforward:

```bash
curl -X DELETE "https://localhost:9200/novapulse-candles-default-2026.01.*"
```

### Monitoring

The ESClient exposes internal counters via the dashboard API:

| Metric | Description |
|--------|-------------|
| `es_docs_indexed` | Total documents successfully indexed |
| `es_docs_failed` | Total documents that failed indexing |
| `es_bulk_flushes` | Number of bulk flush operations |
| `es_buffer_size` | Current buffer depth |
| `es_last_flush_ts` | Timestamp of last successful flush |

These are available at `GET /api/metrics` when the dashboard is running.

---

## Dependency Chain

```
IngestionManager ──polls──> External APIs (alternative.me, CoinGecko, CryptoPanic, on-chain)
       |
       v
   ESClient ──bulk index──> Elasticsearch cluster
       ^
       |
BotEngine ──trade/candle/book events──> ESClient
       |
       v
TrainingDataProvider ──queries──> Elasticsearch ──enriches──> ModelTrainer
```

ES is a leaf dependency. If ES is unreachable, the buffer accumulates until memory pressure triggers a warning and oldest entries are dropped (FIFO eviction at 10x `bulk_max_size`). The trading engine is never blocked by ES operations.
