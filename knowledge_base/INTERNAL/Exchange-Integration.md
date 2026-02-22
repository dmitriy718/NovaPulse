# NovaPulse Exchange Integration

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

NovaPulse integrates with two cryptocurrency exchanges:
- **Kraken** (primary): WebSocket v2 for real-time data + REST for orders and historical data
- **Coinbase** (secondary): Advanced Trade REST API with JWT auth + WebSocket for real-time data

Both exchanges are wrapped behind a common interface so the engine, executor, and risk manager are exchange-agnostic.

---

## Exception Hierarchy

**File:** `src/exchange/exceptions.py`

All exchange operations use a typed exception hierarchy that enables callers to distinguish transient vs permanent failures:

```
ExchangeError (base)
  |
  +-- TransientExchangeError (retry-safe)
  |     |
  |     +-- RateLimitError (backoff + retry)
  |           .retry_after: float  (seconds to wait)
  |
  +-- PermanentExchangeError (non-recoverable)
        |
        +-- AuthenticationError (bad API key/secret/nonce)
        |
        +-- InsufficientFundsError (not enough balance)
        |
        +-- InvalidOrderError (bad pair, size, price)
```

### Retry Strategy by Exception Type

| Exception | Retry? | Behavior |
|-----------|--------|----------|
| `TransientExchangeError` | Yes | Exponential backoff: 1s, 2s, 4s |
| `RateLimitError` | Yes | Use `retry_after` or exponential backoff |
| `PermanentExchangeError` | No | Log error, abort operation |
| `AuthenticationError` | No | Log critical, abort |
| `InsufficientFundsError` | No | Log warning, skip trade |
| `InvalidOrderError` | No | Log warning, skip trade |

---

## Kraken Integration

### Kraken REST Client

**File:** `src/exchange/kraken_rest.py`
**Class:** `KrakenRESTClient`

#### Authentication
- HMAC-SHA512 signature using API key + secret
- Nonce-based replay prevention (monotonically increasing, collision-safe)
- Time synchronization with exchange on initialization

#### Initialization
```python
rest = KrakenRESTClient(api_key="...", api_secret="...")
await rest.initialize()  # REQUIRED before any API call
```

The `initialize()` method:
1. Creates an `httpx.AsyncClient` with connection pooling (20 max connections, 10 keepalive)
2. Synchronizes local clock with Kraken server time
3. Stores time offset for nonce accuracy

#### Rate Limiting
- Semaphore-based: `rate_limit_per_second` (default 15)
- Automatic retry with exponential backoff on 429 responses
- Max retries: 5 (configurable)
- Retry base delay: 1.0s (configurable)

#### Pair Name Mapping

Kraken uses non-standard pair names internally:

| NovaPulse Pair | Kraken Internal |
|----------------|----------------|
| BTC/USD | XXBTZUSD |
| ETH/USD | XETHZUSD |
| SOL/USD | SOLUSD |
| XRP/USD | XXRPZUSD |
| ADA/USD | ADAUSD |
| DOT/USD | DOTUSD |
| AVAX/USD | AVAXUSD |
| LINK/USD | LINKUSD |

#### Key Methods

| Method | Description |
|--------|-------------|
| `place_order(pair, side, order_type, volume, price, ...)` | Place market/limit/stop-loss order |
| `cancel_order(txid)` | Cancel an open order |
| `get_open_orders()` | Fetch all open orders |
| `get_closed_orders()` | Fetch recently closed orders |
| `get_order_info(txid)` | Query single order details |
| `get_ohlc(pair, interval, since)` | Fetch OHLC candle data (max 720 bars/call) |
| `get_min_order_size(pair)` | Get minimum order volume for a pair |
| `get_pair_decimals(pair)` | Get price and lot decimal precision |
| `get_trades_history(start, end)` | Fetch trade execution history |

#### Order Deduplication
Uses an `OrderedDict` of recent client order IDs to prevent double orders from network retries or race conditions.

#### OHLC Warmup Limitation
Kraken returns max 720 bars per OHLC API call. For warmup requiring > 720 bars, two sequential calls are made:
1. First call with `since` set to get the older batch
2. Second call with `since` set to the end of the first batch

### Kraken WebSocket v2

**File:** `src/exchange/kraken_ws.py`
**Class:** `KrakenWebSocketClient`

Subscribes to real-time market data streams:

| Channel | Data | Update Rate |
|---------|------|-------------|
| `ticker` | Best bid/ask, last price, volume | Every tick |
| `ohlc` | Open/High/Low/Close/Volume candles | On candle update |
| `book` | Order book levels (bids + asks) | On book change |
| `trade` | Individual trade executions | On each trade |

#### Auto-Reconnect
- Detects disconnects and automatically reconnects with exponential backoff
- Resubscribes to all channels after reconnect
- Handles Kraken error code 1013 ("Market data unavailable") with retry
- Reports `is_connected` status for health monitoring

#### Event-Driven Scanning
When a new OHLC bar closes (detected by comparing bar timestamps), the pair is enqueued for immediate scanning. This replaces the old time-based polling approach and ensures the bot reacts to completed candles without delay.

#### Price Move Triggers
If price moves more than `event_price_move_pct` (default 0.5%) since the last scan, the pair is also enqueued for scanning, even if no candle has closed.

---

## Coinbase Integration

### Coinbase REST Client

**File:** `src/exchange/coinbase_rest.py`
**Class:** `CoinbaseRESTClient`

#### Authentication
- JWT (ES256) using Coinbase CDP API keys
- Private key PEM format
- Signed requests for authenticated endpoints only

#### Key Methods

Same interface as Kraken REST client:
- `place_order(pair, side, order_type, volume, price, ...)`
- `cancel_order(order_id)`
- `get_ohlc(pair, interval, since)`
- And other standard exchange operations

### Coinbase WebSocket

**File:** `src/exchange/coinbase_ws.py`
**Class:** `CoinbaseWebSocketClient`

Provides the same data streams as Kraken WS for real-time ticker, candle, and order book data.

---

## Order Flow: Entry to Exit

### Entry Flow

```
Signal arrives from ConfluenceDetector
    |
    v
1. Validate signal (age, confidence, direction)
    |
    v
2. Check pre-trade gates:
   - Quiet hours filter
   - Rate throttle (max_trades_per_hour)
   - Duplicate pair check (no two positions on same pair)
   - Correlation group limit (max 2 per group)
   - Strategy cooldown check
    |
    v
3. Calculate position size (RiskManager)
   - Fixed fractional sizing + Kelly cap
   - Apply all adjustment factors
    |
    v
4. Determine limit price from ticker (ask for buy, bid for sell)
    |
    v
5. Place limit order:
   Paper mode: _paper_fill() - simulated fill with micro-slippage
   Live mode:  _live_fill() - real order on exchange
    |
    v
6. Limit chase (live mode only):
   - Wait for fill (timeout per attempt)
   - If not filled, cancel and reprice at current best ask/bid
   - Up to N attempts (limit_chase_attempts, default 2)
   - Delay between attempts: limit_chase_delay_seconds (default 2s)
    |
    v
7. Market fallback (if limit_fallback_to_market: true):
   - If all limit attempts fail and not post_only
   - Places a market order as fallback
    |
    v
8. Post-fill:
   - Shift SL/TP to match actual fill price
   - Record trade in DB
   - Register with RiskManager
   - Initialize stop loss state
   - Place exchange-native stop order (live mode)
   - Capture ML features and order book snapshot
```

### Exit Flow

```
Position management loop (every 2 seconds)
    |
    v
1. Check data freshness (skip if stale > 120s)
    |
    v
2. Check max trade duration (auto-close if exceeded)
    |
    v
3. Update trailing stop
    |
    v
4. Check stop-out condition
   - If hit: close position
    |
    v
5. Check smart exit tiers (if enabled)
   - If tier triggered: partial close
    |
    v
6. Check take profit
   - If hit: close position
    |
    v
7. Persist updated stop loss state to DB
   - Update exchange stop order if SL moved > 0.5%
```

### Close Position Flow (Live Mode)

```
1. Cancel exchange-native stop order
    |
    v
2. Place market exit order with 3-retry logic:
   - PermanentExchangeError: no retry, mark as error
   - RateLimitError: backoff using retry_after, then retry
   - TransientExchangeError: exponential backoff, then retry
   - Generic exception: exponential backoff, then retry
    |
    v
3. Calculate net P&L:
   - Gross PnL = (exit - entry) * quantity [or inverse for shorts]
   - Entry fee = entry_price * quantity * entry_fee_rate
   - Exit fee = exit_price * quantity * taker_fee_rate
   - Net PnL = Gross PnL - entry_fee - exit_fee
   - Add accumulated partial P&L from smart exit
    |
    v
4. Update DB: close_trade with PnL, fees, exit price
    |
    v
5. Update ML label (1=win, 0=loss)
    |
    v
6. Feed to continuous learner (online ML update)
    |
    v
7. Update RiskManager: close_position(pnl)
   - Triggers global cooldown if loss
   - Updates bankroll, streaks, drawdown
    |
    v
8. Notify strategy result callback
   - Feeds back to ConfluenceDetector for adaptive weighting
```

---

## Fee Model

| Fee Type | Default Rate | When Used |
|----------|-------------|-----------|
| Maker fee | 0.16% | Limit orders (post_only in live) |
| Taker fee | 0.26% | Market orders, limit fills |

The bot tracks both entry and exit fees separately. Entry fee rate is stored in trade metadata at entry time and used at exit for accurate P&L calculation.

### Config

```yaml
exchange:
  maker_fee: 0.0016
  taker_fee: 0.0026
  post_only: false
  limit_chase_attempts: 2
  limit_chase_delay_seconds: 2.0
  limit_fallback_to_market: true
```

---

## Multi-Exchange Mode

When `TRADING_ACCOUNTS` or `TRADING_EXCHANGES` is set, multiple `BotEngine` instances run in parallel:

```
TRADING_ACCOUNTS="main:kraken,swing:coinbase"
    |
    +-- BotEngine(exchange=kraken, account=main)
    |     - Own DB: data/trading_kraken_main.db
    |     - Own REST client with MAIN_KRAKEN_API_KEY / MAIN_KRAKEN_API_SECRET
    |     - Own WebSocket connection
    |
    +-- BotEngine(exchange=coinbase, account=swing)
    |     - Own DB: data/trading_coinbase_swing.db
    |     - Own REST client with SWING_COINBASE_API_KEY
    |     - Own WebSocket connection
    |
    v
MultiEngineHub (wraps all engines for dashboard queries)
MultiControlRouter (routes pause/resume/close_all to all engines)
Single DashboardServer (shared uvicorn instance)
```

API keys are resolved by convention: `{ACCOUNT_PREFIX}_{EXCHANGE_NAME}_API_KEY` and `{ACCOUNT_PREFIX}_{EXCHANGE_NAME}_API_SECRET` (uppercased).

---

## Connection Health

The health monitor in `BotEngine` tracks:
- **WebSocket connection status:** `ws_client.is_connected`
- **Data freshness:** `market_data.is_stale(pair, max_age_seconds=180)`
- **REST client responsiveness:** periodic health check calls

If WebSocket is disconnected for > 5 minutes, the circuit breaker can auto-pause trading (see Risk Management doc).
