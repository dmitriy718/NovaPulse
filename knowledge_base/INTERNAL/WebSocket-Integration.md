# NovaPulse WebSocket Integration

**Version:** 5.0.0
**Last Updated:** 2026-02-27

---

## Overview

NovaPulse uses WebSocket connections for real-time market data streaming. The WebSocket layer provides ticker updates, OHLCV bar data, order book snapshots/deltas, and trade stream data. All WS data flows into the `MarketDataCache`, which the scan loop and strategies read from. WebSocket connections are resilient with automatic reconnection, exponential backoff, and heartbeat monitoring.

---

## KrakenWebSocketClient

**File:** `src/exchange/kraken_ws.py` (~410 lines)
**Class:** `KrakenWebSocketClient`

### Protocol

Kraken WS v2 uses JSON-formatted messages over a standard WebSocket connection. The endpoint is `wss://ws.kraken.com/v2` (public data) or `wss://ws-auth.kraken.com/v2` (private, authenticated).

NovaPulse uses the **public** endpoint only -- order management goes through the REST API. No WS authentication is needed.

### Subscriptions

| Channel | Data | Update Frequency | Purpose |
|---------|------|-------------------|---------|
| `ticker` | Best bid/ask, last price, 24h volume | On every trade | Spread calculation, price display |
| `ohlc` | 1-minute OHLCV bars | On bar close + interim updates | Indicator computation, bar cache |
| `book` | L2 order book (10 levels) | Snapshot + incremental deltas | Order book imbalance, spread analysis |
| `trade` | Individual trades | On every trade | Trade flow analysis, event triggers |

### Subscription Message Format

```json
{
  "method": "subscribe",
  "params": {
    "channel": "ohlc",
    "symbol": ["BTC/USD", "ETH/USD"],
    "interval": 1
  }
}
```

Subscriptions are batched: all pairs are subscribed in a single message per channel, not one message per pair.

### Connection Lifecycle

```
1. connect()
   -> websockets.connect(uri, ping_interval=20, ping_timeout=10)
   -> Subscribe to all channels for configured pairs
   -> Start _message_loop() and _heartbeat_monitor() tasks

2. _message_loop()
   -> Reads messages in a loop
   -> Routes to handler based on channel:
      ticker  -> _handle_ticker()
      ohlc    -> _handle_ohlc()
      book    -> _handle_book()
      trade   -> _handle_trade()
   -> On ConnectionClosed: trigger reconnect

3. _heartbeat_monitor()
   -> Every 30s, checks time since last message
   -> If > 60s with no message: force disconnect + reconnect
   -> Guards against silent connection drops

4. disconnect()
   -> Cancel message loop and heartbeat tasks
   -> Close WebSocket connection
```

### Reconnection Strategy

On disconnect (network error, server close, heartbeat timeout), the client reconnects with exponential backoff:

| Attempt | Delay | Cumulative |
|---------|-------|------------|
| 1 | 1s | 1s |
| 2 | 2s | 3s |
| 3 | 4s | 7s |
| 4 | 8s | 15s |
| 5 | 16s | 31s |
| 6-50 | 30s (capped) | -- |

Maximum reconnection attempts: **50**. After 50 failed attempts, the client logs a CRITICAL error and stops trying. The health monitor detects the dead WS and triggers a circuit breaker.

### WS 1013 Close Code

Kraken sends close code 1013 ("Try Again Later") during maintenance or overload. This is handled identically to a network disconnect -- the client waits for the backoff delay and reconnects. It is not treated as an error.

```python
except websockets.ConnectionClosedError as e:
    if e.code == 1013:
        logger.info("Kraken WS 1013 (Try Again Later), reconnecting...")
    else:
        logger.warning("Kraken WS closed: code=%s reason=%s", e.code, e.reason)
    await self._reconnect()
```

### Order Book Management

The `book` channel sends a full **snapshot** on subscription, followed by **incremental updates** (deltas). The client maintains a local order book mirror:

```python
def _handle_book(self, msg):
    pair = msg["data"]["symbol"]
    if msg["type"] == "snapshot":
        self._books[pair] = {
            "bids": {price: qty for price, qty in msg["data"]["bids"]},
            "asks": {price: qty for price, qty in msg["data"]["asks"]},
        }
    elif msg["type"] == "update":
        for price, qty in msg["data"].get("bids", []):
            if qty == 0:
                self._books[pair]["bids"].pop(price, None)
            else:
                self._books[pair]["bids"][price] = qty
        # same for asks
```

Book data is pushed to `MarketDataCache.update_book()` after each snapshot or delta application.

### Message Routing to BotEngine

The WS client holds a reference to callback functions registered by the engine:

```python
ws.on_ticker = engine._handle_ticker_update
ws.on_bar_close = engine._handle_bar_close
ws.on_book_update = engine._handle_book_update
ws.on_trade = engine._handle_trade_update
```

The `on_bar_close` callback is the primary trigger for the event-driven scan loop. When a 1-minute bar closes, the engine evaluates whether to scan (based on indicator changes and event thresholds).

---

## CoinbaseWebSocketClient

**File:** `src/exchange/coinbase_ws.py` (~394 lines)
**Class:** `CoinbaseWebSocketClient`

### Protocol

Coinbase Advanced Trade WebSocket at `wss://advanced-trade-ws.coinbase.com`. Messages are JSON-formatted.

### Subscriptions

| Channel | Data | Purpose |
|---------|------|---------|
| `ticker` | Best bid/ask, last price, volume | Price tracking, spread |
| `candles` | 1-minute OHLCV (when available) | Bar data fallback |

### No Authentication

The Coinbase WS client does **not** authenticate. This means:

- No real-time fill notifications (fills are polled via REST)
- No private order updates
- Public market data only

This is a deliberate design choice: Coinbase WS authentication requires JWT signing on every message, adding complexity. Since order management uses REST anyway, the WS layer only needs public data.

### REST Candle Polling Fallback

Coinbase's WS candle channel can be unreliable for some pairs. The engine runs a parallel `_rest_candle_poll_loop` that fetches 1-minute candles via REST every 60 seconds. The poll loop has per-pair error handling to skip invalid pairs (USDC/USD, TRX/USD, XAUT/USD) that return errors:

```python
async def _rest_candle_poll_loop(self):
    while True:
        for pair in self._pairs:
            if pair in self._invalid_pairs:
                continue
            try:
                candles = await self._rest.get_candles(pair, "ONE_MINUTE", limit=5)
                self._market_data.update_candles(pair, candles)
            except PermanentExchangeError:
                self._invalid_pairs.add(pair)
                logger.warning("Marking %s as invalid, excluding from polls", pair)
            except TransientExchangeError:
                pass  # retry next cycle
        await asyncio.sleep(60)
```

### Message Normalization

Coinbase messages are normalized to the same internal format as Kraken before being passed to the engine. This allows the engine to be exchange-agnostic:

```python
# Internal ticker format (exchange-agnostic):
{
    "pair": "BTC/USD",
    "bid": 65432.10,
    "ask": 65433.50,
    "last": 65432.80,
    "volume_24h": 12345.67,
    "timestamp": 1708790400.0
}
```

---

## MarketDataCache

**File:** `src/exchange/market_data.py` (~414 lines)
**Class:** `MarketDataCache`

Central in-memory store for all market data. Both WS clients and REST polling write into this cache; the scan loop and strategies read from it.

### RingBuffer OHLCV Storage

Per-pair OHLCV data is stored in fixed-size NumPy ring buffers:

```python
class RingBuffer:
    def __init__(self, capacity: int):
        self.data = np.full(capacity, np.nan, dtype=np.float64)
        self.index = 0
        self.count = 0

    def append(self, value: float):
        self.data[self.index % len(self.data)] = value
        self.index += 1
        self.count = min(self.count + 1, len(self.data))
```

Each pair has 6 ring buffers: `opens`, `highs`, `lows`, `closes`, `volumes`, `times`. Default capacity: 500 bars (configurable via `market_data.ring_buffer_size`).

The `to_array()` method returns data in chronological order (oldest first), handling the wrap-around:

```python
def to_array(self) -> np.ndarray:
    if self.count < len(self.data):
        return self.data[:self.count].copy()
    start = self.index % len(self.data)
    return np.concatenate([self.data[start:], self.data[:start]])
```

### Ticker Cache

Latest ticker data per pair, updated on every WS ticker message:

```python
self._tickers: Dict[str, TickerData] = {}

@dataclass
class TickerData:
    pair: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    timestamp: float
```

### Order Book Cache

Local mirror of the L2 order book per pair, updated from WS book snapshots and deltas:

```python
self._books: Dict[str, OrderBookData] = {}

@dataclass
class OrderBookData:
    pair: str
    bids: List[Tuple[float, float]]  # [(price, qty), ...] sorted desc
    asks: List[Tuple[float, float]]  # [(price, qty), ...] sorted asc
    timestamp: float
```

### Staleness Tracking

Each data type tracks its last update timestamp. The health monitor checks staleness:

```python
def is_stale(self, pair: str, data_type: str, max_age_seconds: float = 120) -> bool:
    last_update = self._last_update.get(f"{pair}:{data_type}", 0)
    return (time.time() - last_update) > max_age_seconds
```

Data types tracked: `ticker`, `ohlc`, `book`. Default staleness threshold: 120 seconds. Stale data triggers a warning in the health monitor; sustained staleness (> 5 minutes) triggers a circuit breaker that pauses trading for the affected pair.

### Key Methods

| Method | Description |
|--------|-------------|
| `update_ticker(pair, ticker_data)` | Update ticker cache |
| `update_candle(pair, ohlcv)` | Append to ring buffers |
| `update_book(pair, book_data)` | Replace order book snapshot |
| `get_closes(pair)` | Return close prices as NumPy array |
| `get_highs(pair)` | Return high prices as NumPy array |
| `get_lows(pair)` | Return low prices as NumPy array |
| `get_volumes(pair)` | Return volumes as NumPy array |
| `get_latest_price(pair)` | Return last ticker price |
| `get_spread(pair)` | Return (bid, ask, spread_pct) |
| `is_stale(pair, data_type)` | Check data freshness |

---

## Event-Driven Scanning

The scan loop does not run on a fixed timer. It is triggered by market events:

1. **Bar close:** When a 1-minute bar completes, the `on_bar_close` callback fires. This is the primary scan trigger.
2. **Price move:** If the price moves more than `event_price_move_pct` (default: 0.5%) since the last scan, a scan is triggered.
3. **Minimum interval:** Even without events, the scan loop runs at least once every `max_scan_interval_seconds` (default: 300s) as a safety net.

```python
async def _scan_loop(self):
    while True:
        event = await self._scan_event.wait()  # blocks until triggered
        if event == "bar_close" or event == "price_move":
            await self._run_scan()
        self._scan_event.clear()
```

### Config Keys

```yaml
market_data:
  ring_buffer_size: 500                  # bars per pair
  staleness_threshold_seconds: 120       # stale data warning
  circuit_breaker_seconds: 300           # stale data -> pause pair

scanning:
  event_price_move_pct: 0.5             # price move trigger threshold
  max_scan_interval_seconds: 300         # safety net scan interval
```
