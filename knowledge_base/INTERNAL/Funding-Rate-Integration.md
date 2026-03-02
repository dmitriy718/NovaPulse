# Funding Rate Integration

**Version:** 5.0.0
**Date:** 2026-02-27
**Sources:**
- `src/exchange/funding_rates.py` (FundingRateClient)
- `src/strategies/funding_rate.py` (FundingRateStrategy)
- `src/ai/confluence.py` (injection wiring)

---

## Overview

NovaPulse ingests perpetual futures funding rates from Kraken Futures as a sentiment indicator. Extreme funding rates indicate crowded positioning -- when longs are paying shorts (positive funding), a reversal SHORT may form; when shorts are paying longs (negative funding), a LONG setup may develop. The data flows through a dedicated async client, a strategy, and into the confluence engine.

---

## FundingRateClient

**File:** `src/exchange/funding_rates.py`
**Class:** `FundingRateClient`

### Data Source

- **Endpoint:** `GET https://futures.kraken.com/derivatives/api/v3/tickers`
- **Authentication:** None required (public API).
- **HTTP client:** `httpx.AsyncClient` with 10-second timeout.
- **Payload:** JSON with a `tickers` array; each ticker has `symbol`, `fundingRate`, and other fields.

### Symbol Mapping

Kraken Futures uses perpetual contract symbols (e.g., `PF_XBTUSD`). The client maps these to spot pair names via a static dict:

```python
_FUTURES_TO_SPOT: Dict[str, str] = {
    "PF_XBTUSD": "BTC/USD",
    "PF_ETHUSD": "ETH/USD",
    "PF_SOLUSD": "SOL/USD",
    "PF_XRPUSD": "XRP/USD",
    "PF_ADAUSD": "ADA/USD",
    "PF_DOTUSD": "DOT/USD",
    "PF_AVAXUSD": "AVAX/USD",
    "PF_LINKUSD": "LINK/USD",
}
```

Only symbols present in this mapping are returned. Adding new pairs requires updating this dict.

### Caching

- **TTL:** 5 minutes (300 seconds), configurable via `cache_ttl` parameter (minimum 60s).
- **Thread safety:** `asyncio.Lock` with double-checked locking pattern.
- **Cache invalidation:** If fetch fails, stale cache is returned (no empty result).

```python
async def get_all_rates(self) -> Dict[str, float]:
    now = time.time()
    if (now - self._cache_ts) < self._cache_ttl and self._cache:
        return dict(self._cache)

    async with self._lock:
        # Double-check after acquiring lock
        if (time.time() - self._cache_ts) < self._cache_ttl and self._cache:
            return dict(self._cache)
        rates = await self._fetch_rates()
        if rates:
            self._cache = rates
            self._cache_ts = time.time()
        return dict(self._cache)
```

### API

| Method                          | Returns                    | Description                           |
|---------------------------------|----------------------------|---------------------------------------|
| `get_funding_rate(pair)`        | `Optional[float]`          | Rate for a single spot pair           |
| `get_all_rates()`              | `Dict[str, float]`         | All mapped rates (cached)             |

---

## FundingRateStrategy

**File:** `src/strategies/funding_rate.py`
**Class:** `FundingRateStrategy(BaseStrategy)`

### Configuration

| Parameter              | Default | Description                                      |
|------------------------|---------|--------------------------------------------------|
| `funding_extreme_pct`  | 0.01    | Threshold percentage for "extreme" funding rate  |
| `weight`               | 0.10    | Confluence weight                                |
| `enabled`              | True    | Strategy toggle                                  |

The `funding_extreme_pct` value is divided by 100 internally to convert from percentage to decimal (`0.01 / 100 = 0.0001`).

### Signal Logic

**LONG entry** (extreme negative funding):

1. `funding_rate < -extreme` (shorts paying longs heavily)
2. RSI crossing above 50 (`prev_rsi < 50 and curr_rsi >= 50`) OR momentum turning positive (`curr_mom > prev_mom and curr_mom > 0`)
3. NOT in a strong bearish trend (ADX > 40 + EMA12 < EMA26)

**SHORT entry** (extreme positive funding):

1. `funding_rate > extreme` (longs paying shorts heavily)
2. RSI crossing below 50 OR momentum turning negative
3. NOT in a strong bullish trend (ADX > 40 + EMA12 > EMA26)

### Strength and Confidence Scoring

Base strength: 0.40. Funding extremity bonus: `min(funding_excess * 50, 0.20)` where `funding_excess = abs(funding_rate) - extreme`.

Confidence modifiers:
- RSI crossing: +0.10
- Momentum confirming: +0.10
- Low ADX (range regime, ADX < 25): +0.05

### SL/TP

- Stop loss: **2.0x ATR**
- Take profit: **3.0x ATR**
- Computed via `compute_sl_tp()` with fee adjustment.

### Indicators Used

| Indicator | Period | Source          |
|-----------|--------|-----------------|
| RSI       | 14     | indicator_cache |
| ATR       | 14     | indicator_cache |
| ADX       | 14     | indicator_cache |
| Momentum  | 10     | indicator_cache |
| EMA       | 12, 26 | indicator_cache |

---

## Engine Wiring

### Initialization

The FundingRateClient is initialized during `_init_exchange()` in BotEngine:

```python
self.funding_rate_client = FundingRateClient()
```

### Scan Loop Integration

Before each scan cycle, the engine fetches rates and injects them into the confluence detector:

```python
rates = await self.funding_rate_client.get_all_rates()
self.confluence.set_funding_rates(rates)
```

The confluence detector stores these in `_funding_rates` and passes them through to every strategy via `kwargs`:

```python
signal = await strategy.analyze(
    pair, closes, highs, lows, volumes,
    ...,
    funding_rates=self._funding_rates,
)
```

Only `FundingRateStrategy` reads `kwargs.get("funding_rates")`; all other strategies ignore the kwarg.

### Confluence Family Classification

FundingRateStrategy belongs to the `"sentiment"` family in the confluence detector's `_STRATEGY_FAMILIES` map. This means it contributes to the family diversity bonus independently from all other strategy families.

### Regime Multipliers

Default regime weight multipliers for `funding_rate`:

| Regime     | Multiplier | Reasoning                                     |
|------------|-----------|-----------------------------------------------|
| Trending   | 0.9       | Slightly downweighted (trend-following preferred)|
| Ranging    | 1.2       | Upweighted (mean-reversion sentiment plays well) |
| High vol   | 1.1       | Extreme funding more meaningful in vol spikes    |
| Low vol    | 0.9       | Less actionable in calm markets                  |
