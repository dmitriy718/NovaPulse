# Exchange Integrations

## Kraken

Modules:
- REST: `src/exchange/kraken_rest.py`
- WS: `src/exchange/kraken_ws.py`

Key notes:
- REST client includes rate limiting, retries, nonce management, and order ID deduplication.

## Coinbase

Modules:
- REST: `src/exchange/coinbase_rest.py`
- WS: `src/exchange/coinbase_ws.py`

Key notes:
- WS candles channel limitations exist; the engine uses REST candle polling for 1m candles where needed.
- Subscriptions are additive per channel (merged union list).

## Pair formats

Internal normalized format:
- `BTC/USD`, `ETH/USD`

Coinbase product ids:
- `BTC-USD` (converted internally by REST/WS layers)

