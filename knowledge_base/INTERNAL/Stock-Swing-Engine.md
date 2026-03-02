# NovaPulse Stock Swing Trading Engine

**Version:** 5.0.0
**Last Updated:** 2026-02-27

---

## Overview

The stock swing trading engine is a dedicated subsystem for trading U.S. equities on daily timeframes. It runs alongside the crypto engines in the multi-engine architecture but has its own data pipeline (Polygon.io), broker (Alpaca), universe scanner, and signal generation logic. Unlike the crypto engine's multi-strategy confluence model, the stock engine uses a single composite swing signal with strict entry criteria.

---

## Component Map

```
src/stocks/
  swing_engine.py      StockSwingEngine     (~1199 lines)  Main engine loop
  polygon_client.py    PolygonClient        (~278 lines)   Market data
  alpaca_client.py     AlpacaClient         (~207 lines)   Order execution
  universe.py          UniverseScanner      (~245 lines)   Dynamic stock universe
```

**Database:** `trading_stocks_default.db` (same schema as crypto, `tenant_id = "stocks:default"`)

---

## StockSwingEngine

**File:** `src/stocks/swing_engine.py` (~1199 lines)
**Class:** `StockSwingEngine`

The main orchestrator for stock trading. It manages the scan loop, position monitoring, and coordination with the priority scheduler.

### Background Tasks

| Task | Interval | Description |
|------|----------|-------------|
| `_scan_loop` | `scan_interval_seconds` (120s) | Iterates universe, computes indicators, generates signals |
| `_position_monitor` | 10s | Checks stop-loss, take-profit, trailing stops on open positions |
| `_universe_refresh_loop` | 3600s (60 min) | Refreshes dynamic universe during market hours |
| `_bar_cache_update` | 300s (5 min) | Fetches latest daily bars for all universe symbols |

### Market Hours Guard

All scanning and trading activity is gated by market hours:

```python
def _is_market_open(self) -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close
```

Outside market hours, the scan loop sleeps. The priority scheduler in `main.py` additionally pauses the crypto engine during stock hours to avoid resource contention and to focus capital allocation.

### Signal Generation

A swing entry signal requires ALL of the following conditions simultaneously:

```
1. Price > EMA(20) > EMA(50)           # aligned uptrend
2. RSI(14) between 45 and 72           # not overbought, not oversold
3. 5-day momentum > 0                  # positive short-term trend
4. Volume > 0.8 * SMA(volume, 20)      # adequate volume
```

Signals are **long-only** in the current implementation. Short selling is not supported.

### Stop-Loss and Take-Profit

- **Initial stop-loss:** ATR(14) * 2.0 below entry, floored at 3.0%
- **Take-profit:** ATR(14) * 4.0 above entry, floored at 8.0%
- **Trailing stop:** activates at 5% profit, trails at ATR(14) * 1.5

### Position Sizing

Stock positions use the same fixed-fractional risk model as crypto:

```
risk_amount = bankroll * max_risk_per_trade
position_size_usd = risk_amount / stop_loss_distance_pct
position_size_shares = floor(position_size_usd / current_price)
```

Minimum order: 1 share. Maximum position: `max_position_pct` of bankroll (default: 15%).

### Bar Cache

The engine maintains an in-memory cache of the last `lookback_bars` (120) daily bars per symbol. Bars are stored as NumPy arrays for fast indicator computation. The cache is populated on startup and incrementally updated as new bars arrive.

```python
self._bar_cache: Dict[str, Dict[str, np.ndarray]] = {}
# { "AAPL": { "close": np.array([...]), "high": ..., "low": ..., "volume": ..., "open": ..., "time": ... } }
```

---

## PolygonClient

**File:** `src/stocks/polygon_client.py` (~278 lines)
**Class:** `PolygonClient`

Async HTTP client for Polygon.io REST API. Used for daily bar data and universe scanning.

### API Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `get_daily_bars(symbol, from_date, to_date)` | `/v2/aggs/ticker/{symbol}/range/1/day/{from}/{to}` | Historical daily OHLCV for a single symbol |
| `get_grouped_daily_bars(date)` | `/v2/aggs/grouped/locale/us/market/stocks/{date}` | All US stock bars for a single date (universe scanning) |

### Free Tier Constraints

Polygon's free tier does **not** grant access to the `/v3/snapshot` endpoint (returns 403). The universe scanner uses `get_grouped_daily_bars()` as the fallback, which works on the free tier and returns all symbols for a given date.

### Monday Date Bug (Fixed)

Previous versions used `offset=1` to get the previous trading day, which on Monday yielded Sunday (0 results). The fix uses `offset=3` on Monday to land on Friday:

```python
def _previous_trading_day(self, dt: date) -> date:
    weekday = dt.weekday()
    if weekday == 0:    # Monday -> Friday
        return dt - timedelta(days=3)
    elif weekday == 6:  # Sunday -> Friday
        return dt - timedelta(days=2)
    elif weekday == 5:  # Saturday -> Friday
        return dt - timedelta(days=1)
    else:
        return dt - timedelta(days=1)
```

### Rate Limiting

Free tier: 5 requests/minute. The client uses a `asyncio.Semaphore` and per-request delay to stay within limits. On 429 responses, it retries with exponential backoff (1s, 2s, 4s, max 3 retries).

### Config Keys

```yaml
stocks:
  polygon:
    api_key: "${POLYGON_API_KEY}"
    base_url: "https://api.polygon.io"
    rate_limit_rpm: 5
    max_retries: 3
```

---

## AlpacaClient

**File:** `src/stocks/alpaca_client.py` (~207 lines)
**Class:** `AlpacaClient`

Minimal async client for Alpaca Trading API v2. Handles order submission, cancellation, and account queries.

### Methods

| Method | Description |
|--------|-------------|
| `submit_order(symbol, qty, side, type, time_in_force)` | Submit a market or limit order |
| `cancel_order(order_id)` | Cancel a pending order |
| `get_order(order_id)` | Get order status |
| `list_positions()` | List all open positions |
| `get_account()` | Get account balance and buying power |
| `close_position(symbol)` | Close an open position (market order) |

### Order Types

The engine primarily uses **market orders** for entry and exit. Limit orders are used only for the initial stop-loss placement when `use_bracket_orders` is enabled.

### Authentication

```
ALPACA_API_KEY       -> API key ID
ALPACA_SECRET_KEY    -> API secret key
ALPACA_BASE_URL      -> https://paper-api.alpaca.markets (paper) or https://api.alpaca.markets (live)
```

Paper trading is the default. Set `ALPACA_BASE_URL` to the live endpoint for production.

### Config Keys

```yaml
stocks:
  alpaca:
    api_key: "${ALPACA_API_KEY}"
    secret_key: "${ALPACA_SECRET_KEY}"
    base_url: "${ALPACA_BASE_URL}"
    use_bracket_orders: false
```

---

## UniverseScanner

**File:** `src/stocks/universe.py` (~245 lines)
**Class:** `UniverseScanner`

Dynamically selects which stocks to trade based on liquidity and price filters.

### Universe Composition

```
Total universe: max_universe_size (96)
  = 4 pinned stocks (always included)
  + up to 92 dynamic stocks (ranked by volume)
```

**Pinned stocks:** AAPL, MSFT, NVDA, TSLA -- always in the universe regardless of filters.

### Scanning Process

```
1. Fetch grouped daily bars for previous trading day
   -> get_grouped_daily_bars(previous_trading_day)
   -> Returns ~11,800+ symbols on a typical day

2. Filter:
   -> volume >= min_volume (default: 1,000,000)
   -> price >= min_price (default: 5.00)
   -> price <= max_price (default: 1,000.00)

3. Rank by volume (descending)

4. Take top (max_universe_size - len(pinned_stocks)) symbols

5. Merge with pinned stocks (pinned always first)

6. Store in self._universe: List[str]
```

### Refresh Cycle

The universe refreshes every 60 minutes during market hours. Outside market hours, refreshes are skipped (the previous universe is kept). On engine startup, an immediate refresh is performed.

### Scanner Labels in Multi-Engine

When displayed in the dashboard or logs, stock symbols include the engine label:

```
"AAPL (stocks:default)"    # not plain "AAPL"
```

This distinguishes stock positions from crypto pairs in the unified multi-engine dashboard.

### Config Keys

```yaml
stocks:
  universe:
    max_universe_size: 96
    pinned_symbols: ["AAPL", "MSFT", "NVDA", "TSLA"]
    min_volume: 1000000
    min_price: 5.0
    max_price: 1000.0
    refresh_interval_seconds: 3600
  scan_interval_seconds: 120
  lookback_bars: 120
```

---

## Priority Scheduler

**File:** `main.py`

The priority scheduler coordinates crypto and stock engines to avoid running simultaneously during stock market hours.

```
           NYSE Open                    NYSE Close
              |                              |
  09:30 ET ---+--------- Market Hours -------+--- 16:00 ET
              |                              |
  Crypto:   PAUSED                         RESUMED
  Stocks:   RESUMED                        PAUSED
```

Implementation uses `zoneinfo.ZoneInfo("America/New_York")` for timezone handling. The scheduler polls every 30 seconds and calls `engine.pause()` / `engine.resume()` as needed. Paused engines stop scanning but continue monitoring open positions (stop-loss and take-profit checks remain active).

### Weekend Behavior

Stocks are paused all weekend (Saturday + Sunday). Crypto runs uninterrupted on weekends since there are no stock market hours to yield to.
