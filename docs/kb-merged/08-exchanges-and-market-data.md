# Exchanges and Market Data

## Exchange Selection

Single:

1. `ACTIVE_EXCHANGE` or `EXCHANGE_NAME`

Multi:

1. `TRADING_EXCHANGES=kraken,coinbase`

## Pair Conventions

Configured pairs are typically in the form:

1. `BTC/USD`
1. `ETH/USD`

Exchange clients may map these to native symbols.

Example:

1. Coinbase product ids often look like `BTC-USD`.

## WS vs REST Responsibilities

Typical split:

1. WS provides low-latency price updates and often order book.
1. REST provides candle warmup/backfill and some historical lookups.

## Common Incident: Stale Feed

Symptoms:

1. Many scanner entries are `stale: true`
1. WS reports disconnected
1. "No trades" complaints

Support actions:

1. Check `GET /api/v1/status`
1. Check `GET /api/v1/scanner` and quantify stale pairs
1. Read WS logs for reconnect loops
1. If Coinbase: confirm REST candle poll loop is running
1. Pause trading until data is fresh

## Coinbase-Specific Notes (Support/Dev)

1. WebSocket subscriptions must be additive (do not overwrite previous product ids).
1. Public trade-history requests may fail in some environments; fallbacks are expected.
1. Sandbox environments can have market-data limitations; expect to rely more on REST candle polling and health guards.

Code:

1. `src/exchange/coinbase_ws.py`
1. `src/exchange/coinbase_rest.py`
