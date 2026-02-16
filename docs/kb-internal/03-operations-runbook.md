# Operations Runbook

## Quick health checks

1. Dashboard reachable:
- `GET /api/v1/status`
- `GET /api/v1/scanner`
- WebSocket: `ws://HOST/ws/live`

2. Data freshness:
- Scanner shows `stale: false` for most pairs.
- If many pairs are stale, investigate WS connectivity and REST warmup/backfill.

3. Trading paused:
- `status.paused` indicates whether entries are paused.

## Logs and artifacts

Primary logs:
- `logs/trading_bot.log`
- `logs/errors.log`

DB:
- default: `data/trading.db` (WAL mode)

Model artifacts:
- `models/trade_predictor.tflite`
- `models/normalization.json`

## Safe control actions

Control endpoints:
- `POST /api/v1/control/pause`
- `POST /api/v1/control/resume`
- `POST /api/v1/control/close_all`

Auth:
- Provide `X-API-Key` header.
  - Admin: `DASHBOARD_SECRET_KEY`
  - Tenant keys: API keys mapped to a tenant (if configured)

## Stale data incident

Symptoms:
- Scanner shows many stale pairs.
- WS `ws_connected=false`.

Actions:
1. Check `GET /api/v1/status`.
2. Review logs for WS reconnect loops.
3. If exchange is Coinbase and WS candles are limited, confirm REST candle poll loop is running.
4. If necessary, pause trading until data is fresh.

## Execution incident (missed fills, many cancels)

Actions:
1. Inspect `GET /api/v1/execution` stats.
2. Review `TradeExecutor` logs around `_place_live_order` and `_wait_for_fill`.
3. Consider:
   - spread filter thresholds (`trading.max_spread_pct`)
   - limit chase settings (`exchange.limit_chase_attempts`, delay, market fallback)

## Database incident

If running tests or bot on unsupported Python versions can hang async DB connects.

Action:
- Use Python 3.11 or 3.12 and recreate venv.
- Confirm `pyproject.toml` runtime constraint and `main.py` startup guard.

