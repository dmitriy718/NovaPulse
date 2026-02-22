# NovaPulse Internal FAQ

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## General

### Q: What is NovaPulse?

NovaPulse is a Python asyncio cryptocurrency trading bot that runs 9 technical analysis strategies in parallel, combines their signals through a confluence engine, validates them with AI/ML models, sizes positions using Kelly Criterion, and executes trades on Kraken or Coinbase exchanges. It is deployed as a Docker container with a FastAPI dashboard for monitoring and control.

### Q: What Python versions are supported?

Python 3.11, 3.12, and 3.13.

### Q: What is the difference between "paper" and "live" mode?

- **Paper mode:** Simulates trades with realistic fills (micro-slippage). No real orders are placed. Safe for testing and strategy development. Ephemeral dashboard keys are auto-generated.
- **Live mode:** Places real orders on the exchange. Requires explicit API keys, dashboard admin key, session secret, and password hash. Additional safety checks are enforced at startup.

---

## Trading

### Q: Why is the bot not taking any trades?

Several reasons can prevent trades. Check in this order:

1. **Paused?** Check `/api/v1/status` for `"paused": true`. Resume if manually paused.
2. **Global cooldown?** After a loss, the bot waits 30 minutes by default.
3. **Daily loss limit?** Check risk report for daily P&L vs limit.
4. **Max positions?** Already at `max_concurrent_positions` (default 5).
5. **No signals?** Market may be flat. Check scanner results.
6. **Data stale?** WebSocket may be disconnected. Check `ws_connected`.
7. **Strategies disabled?** Check strategies endpoint for `runtime_disabled`.
8. **Quiet hours?** Check if current UTC hour is in quiet_hours_utc.
9. **Bankroll depleted?** If bankroll <= $0, no trades are allowed.

### Q: What is a "Sure Fire" setup?

A "Sure Fire" setup occurs when 3 or more strategies agree on direction AND the Order Book Imbalance confirms the direction AND confidence exceeds the minimum threshold (0.65). Sure Fire signals get a +0.15 strength bonus and +0.10 confidence bonus.

### Q: Why does the bot use limit orders instead of market orders?

Limit orders provide better execution prices and lower fees (maker vs taker). The bot places a limit order at the current best ask (for buys) or best bid (for sells), then "chases" by repricing if the first attempt doesn't fill. If all limit attempts fail, it can optionally fall back to a market order.

### Q: What happens if a limit order doesn't fill?

The bot uses a chase mechanism:
1. Place limit order at current best price
2. Wait for fill (default 10 second timeout)
3. If not filled, cancel and reprice at the new best price
4. Repeat up to `limit_chase_attempts` (default 2) times
5. If still not filled and `limit_fallback_to_market: true`, place a market order
6. If that also fails, the trade is rejected (no position opened)

### Q: How does multi-timeframe work?

NovaPulse stores 1-minute candles as its base data. For multi-timeframe analysis, it resamples these to 5-minute and 15-minute candles using numpy `reduceat` operations. All 9 strategies run independently on each timeframe. The results are combined:
- The primary timeframe (default: 1-min) drives the direction
- A minimum number of timeframes must agree (default: 2 of 3)
- SL/TP come from the highest agreeing timeframe (wider stops)

### Q: What is canary mode?

Canary mode is a controlled rollout mechanism for live trading:
- Restricts trading to a small set of pairs (default max 2)
- Reduces position sizes (default max $100)
- Reduces risk per trade (default 0.5%)
- Increases confidence threshold (default 0.68)
- Increases confluence threshold (default 3)

Use canary mode as an intermediate step between paper and full live trading.

---

## Risk Management

### Q: Why are stop losses so wide (2.5%)?

On 1-minute candles, ATR is typically 0.06-0.10% of price, which would create unreasonably tight stops. The `compute_sl_tp()` function enforces percentage-based floors:
- Minimum SL: 2.5% from entry
- Minimum TP: 5.0% from entry

These floors prevent constant stop-outs from normal market noise.

### Q: What is the Kelly Criterion and why quarter-Kelly?

Kelly Criterion is a mathematical formula for optimal bet sizing based on edge and win rate. Full Kelly is mathematically optimal for long-term growth but requires exact knowledge of edge, which is impossible in practice. Using full Kelly with imprecise estimates leads to catastrophic losses. Quarter-Kelly (25% of the Kelly-recommended size) provides most of the growth benefit with much less risk of ruin.

In NovaPulse, Kelly only acts as a cap (never increases size beyond fixed fractional) and only activates after 50+ trades with a verified positive edge.

### Q: What triggers the global cooldown?

Every losing trade activates a global cooldown (default 30 minutes). During this period, no new positions can be opened. This prevents emotional/revenge trading and gives the market time to settle.

### Q: What is the drawdown scaling?

As the bankroll drops from its peak, position sizes are automatically reduced:
- < 3% drawdown: full size
- 3-7%: 80% size
- 7-12%: 60% size
- 12-18%: 35% size
- > 18%: 15% size

This protects the bankroll during losing streaks.

---

## Infrastructure

### Q: How do I access the SQLite database?

```bash
# From host (if data/ is a bind mount)
sqlite3 data/trading.db

# From inside the container
docker exec -it novapulse sqlite3 /app/data/trading.db
```

**Warning:** Do not open the database for writing while the bot is running. Read-only queries are safe because of WAL mode.

### Q: How do I reset the bot's trade history and start fresh?

```bash
# Stop the bot
docker compose stop trading-bot

# Delete (or rename) the database
mv data/trading.db data/trading.db.backup

# Remove instance lock
rm -f data/instance.lock

# Restart
docker compose up -d trading-bot
```

The bot will create a fresh database on startup.

### Q: What happens during a container restart?

1. Graceful shutdown: cancel all background tasks (15s timeout), close resources
2. On restart, `main.py` runs preflight checks and instance lock
3. `run_bot()` initializes all subsystems in dependency order
4. `reinitialize_positions()` restores open positions from the database
5. Market data warmup: loads historical candles for all pairs
6. Background tasks resume (scan loop, position loop, WS, health monitor, etc.)

Open positions survive restarts because they are persisted in SQLite and restored.

### Q: How does the instance lock work?

The file `data/instance.lock` prevents duplicate bot processes from running simultaneously. On startup:
1. Check if lock file exists
2. If exists, check if the process that created it is still running
3. If the process is dead, remove the stale lock and create a new one
4. If the process is alive, abort startup

If the lock is stale (e.g., after an OOM kill), delete it manually: `rm data/instance.lock`

### Q: Is Elasticsearch required?

No. Elasticsearch is completely optional. The bot functions fully without it. ES provides:
- Analytics mirror of trade data
- External data collection (Fear & Greed, CoinGecko, CryptoPanic, on-chain)
- Visualization via Kibana

ES is configured as a soft dependency in docker-compose (`required: false`).

### Q: How much disk space does the database use?

Typical sizes after weeks of paper trading:
- `data/trading.db`: 5-50 MB depending on trade count and thought log
- `data/trading.db-wal`: Usually < 10 MB (auto-checkpointed)
- `data/trading.db-shm`: < 1 MB

If the WAL file grows very large, force a checkpoint:
```bash
docker exec novapulse sqlite3 /app/data/trading.db "PRAGMA wal_checkpoint(TRUNCATE)"
```

---

## AI / ML

### Q: What does the TFLite model do?

The TFLite model predicts signal quality (probability of a profitable trade) based on features like RSI, EMA ratio, BB position, ADX, volume ratio, OBI, ATR%, momentum score, trend strength, and spread. Its confidence is blended with the continuous learner: 60% TFLite + 40% online learner (when both are active).

### Q: What is the continuous learner?

An online SGD (Stochastic Gradient Descent) model that updates after every closed trade. It learns from the same features as TFLite but adapts to recent market conditions. It requires no batch retraining -- it learns incrementally from each trade result.

### Q: What if the ML model is missing?

ML components are non-critical. If the TFLite model file is missing or fails to load:
- The bot logs a warning and continues without AI confidence scoring
- Trading signals are scored by confluence + strategy confidence only
- The continuous learner initializes independently

---

## Multi-Tenant

### Q: How does multi-tenant isolation work?

Every database table includes a `tenant_id` column. All queries are scoped by tenant:
- Admin/read keys can target any tenant explicitly
- Tenant API keys are pinned to a specific tenant via hashed lookup
- If a tenant key tries to access another tenant, HTTP 403 is returned
- Inactive tenants are denied access

### Q: How do I create a new tenant?

```bash
docker exec novapulse python -c "
import asyncio, hashlib, secrets
from src.core.database import DatabaseManager
async def main():
    db = DatabaseManager('/app/data/trading.db')
    await db.initialize()
    tenant_id = 'new_tenant'
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    async with db._timed_lock():
        await db._db.execute(
            'INSERT INTO tenants (tenant_id, name, status) VALUES (?, ?, ?)',
            (tenant_id, 'New Tenant', 'active')
        )
        await db._db.execute(
            'INSERT INTO tenant_api_keys (tenant_id, key_hash, label) VALUES (?, ?, ?)',
            (tenant_id, key_hash, 'Initial key')
        )
        await db._db.commit()
    print(f'Tenant created: {tenant_id}')
    print(f'API key: {api_key}')
asyncio.run(main())
"
```

---

## Strategies

### Q: Which strategies were removed in v4.0?

Four strategies were removed due to poor performance:
- **Momentum** (8% WR) - removed
- **Breakout** (0% WR) - replaced by Volatility Squeeze
- **VWAP Momentum Alpha** (33% WR) - replaced by Ichimoku Cloud
- **RSI Mean Reversion** - replaced by Stochastic Divergence

The old strategy files still exist on disk but are no longer imported.

### Q: What are strategy guardrails?

Runtime guardrails evaluate each strategy after every trade close. If a strategy's recent performance (last 30 trades) shows:
- Win rate below 35% AND profit factor below 0.85

The strategy is automatically disabled for 120 minutes (configurable). After the timeout, it re-enables automatically. This prevents strategies from accumulating losses in unfavorable market conditions.

### Q: How does adaptive strategy weighting work?

Each strategy tracks its last 50 trades in a sliding window. A Sharpe-like performance score is computed per market regime. This score becomes a multiplier (0.5x to 1.5x) on the strategy's base weight. Strategies on winning streaks get more influence on the confluence score; struggling strategies get less.

---

## Troubleshooting

### Q: Why do I see "Kraken WS 1013" errors?

Error code 1013 means "Market data unavailable" from Kraken. This is a known Kraken-side issue that typically resolves within minutes. The bot handles it with automatic retry and exponential backoff.

### Q: Why does `get_ohlc` only return 720 bars?

Kraken's OHLC API returns a maximum of 720 bars per call. For warmup requiring more bars (default 500 is fine), the bot makes multiple sequential calls. If you set `warmup_bars > 720`, two API calls are made with appropriate `since` parameters.

### Q: How do I change trading pairs?

Edit `config/config.yaml`:
```yaml
trading:
  pairs:
    - BTC/USD
    - ETH/USD
    - SOL/USD
    - XRP/USD
```

Then restart: `docker compose restart trading-bot`

### Q: How do I view the AI thought feed?

```bash
# Via API
curl -s http://localhost:8090/api/v1/thoughts -H "X-API-Key: $KEY" | python -m json.tool

# Via DB
docker exec novapulse sqlite3 /app/data/trading.db \
  "SELECT timestamp, category, severity, message FROM thought_log ORDER BY id DESC LIMIT 20"
```

### Q: How do I force-close all positions?

```bash
# Via API
curl -X POST http://localhost:8090/api/v1/control/close_all \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"

# Via Telegram (if configured)
# Send /close_all to the bot

# Via DB (emergency, if API is down)
docker exec novapulse sqlite3 /app/data/trading.db \
  "UPDATE trades SET status='closed', exit_price=entry_price, pnl=0, notes='Manual close' WHERE status='open'"
```

**Warning:** The DB-only approach does not place exchange exit orders. In live mode, always use the API or close positions on the exchange manually.
