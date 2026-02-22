# NovaPulse Runbooks

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

Step-by-step incident response procedures for common operational scenarios. Each runbook follows the format: Symptom, Diagnosis, Resolution, Prevention.

---

## 1. Bot Shows OFFLINE / Health Check Failing

### Symptom
- Docker health check reports "unhealthy"
- `/api/v1/health` returns 5xx or times out
- Dashboard not loading

### Diagnosis

```bash
# Check container status
docker ps -a | grep novapulse

# Check if container is restarting
docker inspect novapulse --format='{{.State.Status}} restarts={{.RestartCount}}'

# Check recent logs for crash
docker logs novapulse --tail 200
```

### Resolution

**If container is restarting:**
```bash
# Check for crash reason in logs
docker logs novapulse --tail 500 2>&1 | grep -i "error\|exception\|fatal\|critical"

# Common causes:
# 1. Instance lock from previous crash
rm data/instance.lock
docker compose restart trading-bot

# 2. Database corruption
docker exec novapulse sqlite3 /app/data/trading.db "PRAGMA integrity_check"
# If corrupt, restore from backup or reset

# 3. Config validation failure
docker compose run --rm trading-bot python -c "from src.core.config import get_config; get_config()"

# 4. Port conflict
docker compose down && docker compose up -d trading-bot
```

**If container is stopped:**
```bash
docker compose up -d trading-bot
```

### Prevention
- Monitor container health via Docker events or external monitoring
- Set up alerting on health check failures
- Keep instance.lock in a tmpfs or clean it on startup

---

## 2. WebSocket Disconnected / No Market Data

### Symptom
- Status shows `ws_connected: false`
- Log entries: "WebSocket disconnected" or "Kraken WS 1013"
- Scan loop running but no trades because data is stale

### Diagnosis

```bash
# Check WS status
curl -s http://localhost:8090/api/v1/status -H "X-API-Key: $KEY" | python -m json.tool | grep ws_connected

# Check logs for WS errors
docker logs novapulse --tail 200 2>&1 | grep -i "websocket\|ws.*error\|1013"
```

### Resolution

1. **Kraken 1013 error (Market data unavailable):** This is a known Kraken issue. The bot handles it automatically with retry backoff. Wait 5-10 minutes.

2. **Persistent disconnect:**
   ```bash
   # Restart the container
   docker compose restart trading-bot
   ```

3. **Network issue:**
   ```bash
   # Test connectivity from container
   docker exec novapulse python -c "
   import httpx, asyncio
   async def test():
       async with httpx.AsyncClient() as c:
           r = await c.get('https://api.kraken.com/0/public/Time')
           print(r.status_code, r.text[:100])
   asyncio.run(test())
   "
   ```

4. **Circuit breaker activated:** If the auto-pause-on-WS-disconnect circuit breaker triggered, the bot paused trading. Once WS reconnects, manually resume:
   ```bash
   curl -X POST http://localhost:8090/api/v1/control/resume \
     -H "X-API-Key: $DASHBOARD_ADMIN_KEY"
   ```

### Prevention
- The bot auto-reconnects with exponential backoff
- Circuit breaker pauses trading after 5 minutes of disconnect (configurable)
- Monitor `ws_connected` status in dashboard

---

## 3. Trading Paused / No New Entries

### Symptom
- Bot is running but not opening any new positions
- Status shows `paused: true`
- Thought log shows risk blocks

### Diagnosis

```bash
# Check if manually paused
curl -s http://localhost:8090/api/v1/status -H "X-API-Key: $KEY" | python -m json.tool

# Check thought log for blocks
curl -s http://localhost:8090/api/v1/thoughts -H "X-API-Key: $KEY" | python -m json.tool | head -50

# Check risk report
curl -s http://localhost:8090/api/v1/risk -H "X-API-Key: $KEY" | python -m json.tool
```

### Common Causes and Fixes

| Cause | Log Message | Fix |
|-------|-----------|-----|
| Manual pause | "Trading PAUSED via control" | Resume via API/Telegram |
| Daily loss limit | "Daily loss limit reached" | Wait for midnight UTC reset |
| Global cooldown | "Global cooldown: Ns remaining" | Wait for cooldown to expire |
| Max positions reached | "Max positions reached" | Wait for positions to close |
| Risk of ruin | "Risk of ruin threshold exceeded" | Reduce risk params or add bankroll |
| Consecutive losses | Auto-pause triggered | Resume via API after reviewing strategy |
| Drawdown pause | Auto-pause triggered | Resume via API after reviewing risk |
| Stale data pause | "Data freshness check failed" | Fix WS connection (see Runbook 2) |
| Quiet hours | Trade blocked during quiet hours | Wait for quiet hours to end |
| Rate throttle | "trade-rate limit reached" | Wait or increase max_trades_per_hour |
| Bankroll depleted | "Bankroll depleted" | Reset bankroll or add funds |

### Resolution

```bash
# Resume trading
curl -X POST http://localhost:8090/api/v1/control/resume \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"
```

---

## 4. Exchange Order Failed

### Symptom
- Trade shows in thought log as "Order fill failed"
- Trade status is "error" in database
- Log shows exchange error messages

### Diagnosis

```bash
# Check for exchange errors in logs
docker logs novapulse --tail 200 2>&1 | grep -i "order.*fail\|exchange.*error\|insufficient\|invalid"

# Check for error-status trades
docker exec novapulse python -c "
import asyncio
from src.core.database import DatabaseManager
async def main():
    db = DatabaseManager('/app/data/trading.db')
    await db.initialize()
    async with db._timed_lock():
        cursor = await db._db.execute(
            \"SELECT trade_id, pair, side, status, notes FROM trades WHERE status='error' ORDER BY created_at DESC LIMIT 10\"
        )
        for row in await cursor.fetchall():
            print(dict(row))
asyncio.run(main())
"
```

### Resolution

**AuthenticationError:** Check API key/secret in `.env`. Ensure they have trading permissions on the exchange.

**InsufficientFundsError:** Check exchange balance. The bot does not auto-adjust for available funds -- the position size may exceed available balance.

**InvalidOrderError:** Check if the pair is valid, the volume meets minimum size, and the price has correct decimal precision.

**RateLimitError:** The bot auto-retries with backoff. If persistent, reduce `rate_limit_per_second` in config.

**Exit order failed (3 retries exhausted):** This is critical. The position is marked as "error" in the DB but may still be open on the exchange. Manual intervention required:
1. Check the exchange UI for the open position
2. Close it manually
3. Update the trade in the DB

### Prevention
- Ensure exchange API keys have correct permissions
- Keep sufficient balance for planned position sizes
- Monitor for InsufficientFunds errors

---

## 5. Ghost Positions / Orphan Orders

### Symptom
- Reconciliation log shows "Potential ghost position" or "Potential orphan order"
- DB shows open trades but exchange shows no matching orders

### Diagnosis

```bash
# Check reconciliation logs
docker logs novapulse 2>&1 | grep -i "ghost\|orphan\|reconcil"
```

### Resolution

**Ghost positions (DB open, exchange not):**
- If the order was filled normally, the ghost warning is informational
- If the position was closed externally (e.g., manual close on exchange):
  1. Query the exchange for the order status
  2. Manually update the trade in the DB:
     ```sql
     UPDATE trades SET status='closed', exit_price=<price>, pnl=<pnl>,
       exit_time=datetime('now'), notes='Manually closed on exchange'
     WHERE trade_id='<trade_id>';
     ```

**Orphan orders (exchange open, DB not):**
- Cancel the orphan order on the exchange manually
- Or leave it if it's a deliberate manual order

### Prevention
- Reconciliation runs every 5 minutes automatically
- Do not manually place orders on the exchange while the bot is running

---

## 6. High Memory Usage

### Symptom
- Container approaching 2GB memory limit
- OOM kills (container restarts with exit code 137)

### Diagnosis

```bash
docker stats novapulse --no-stream
docker inspect novapulse --format='{{.State.OOMKilled}}'
```

### Resolution

1. **Increase memory limit** in docker-compose.yml:
   ```yaml
   deploy:
     resources:
       limits:
         memory: 3G
   ```

2. **Reduce data retention:**
   - `monitoring.metrics_retention_hours`: reduce from 72 to 24
   - `dashboard.thought_feed_max`: reduce from 200 to 100
   - ES `buffer_maxlen`: reduce from 10000 to 5000

3. **Reduce pair count:** Fewer pairs = less market data in memory

4. **Reduce warmup bars:** `trading.warmup_bars: 300` (down from 500)

### Prevention
- Monitor container memory usage
- Set up alerts at 80% of memory limit

---

## 7. Database Lock Timeout

### Symptom
- Log entries: "Database lock acquisition timed out - possible deadlock"
- Trades not being recorded
- Dashboard queries timing out

### Diagnosis

```bash
docker logs novapulse 2>&1 | grep -i "lock.*timeout\|deadlock"
```

### Resolution

1. **Restart the container:**
   ```bash
   docker compose restart trading-bot
   ```

2. **Check for WAL file growth:**
   ```bash
   ls -la data/trading.db*
   ```
   If the WAL file is very large (> 100MB), it may need checkpointing:
   ```bash
   docker exec novapulse sqlite3 /app/data/trading.db "PRAGMA wal_checkpoint(TRUNCATE)"
   ```

3. **Check for external DB access:** Do not run `sqlite3` directly against the DB while the bot is running in write mode.

### Prevention
- The DB uses a 30-second lock timeout to prevent indefinite hangs
- WAL mode allows concurrent readers without blocking writes
- Avoid external write access to the DB while the bot is running

---

## 8. ML Model Errors

### Symptom
- Log entries: "TFLite predictor failed" or "Continuous learner update failed"
- AI confidence not being applied to signals

### Diagnosis

```bash
docker logs novapulse 2>&1 | grep -i "tflite\|predictor\|learner\|model.*error"
```

### Resolution

ML failures are **non-blocking** -- the bot continues trading without AI confidence adjustments.

1. **Model file missing:**
   - Check `models/trade_predictor.tflite` exists
   - If missing, the bot runs without TFLite predictions

2. **Model retrain needed:**
   - Wait for auto-retrain (configured via `ml.retrain_interval_hours`)
   - Or trigger manually (requires sufficient training data in `ml_features` table)

3. **Continuous learner crash:**
   - Non-fatal; the learner will reinitialize on next trade close
   - Check for NaN/Inf values in ML features

### Prevention
- Ensure `models/` directory is mounted and writable
- ML components are initialized as NON-CRITICAL -- failures are logged and skipped

---

## 9. Strategy Guardrail Disabled a Strategy

### Symptom
- Log: "Strategy auto-disabled by runtime guardrail"
- Strategy stats show `runtime_disabled: true`

### Diagnosis

```bash
# Check which strategies are disabled
curl -s http://localhost:8090/api/v1/strategies -H "X-API-Key: $KEY" | python -m json.tool | grep -A5 "runtime_disabled"

# Check logs for guardrail triggers
docker logs novapulse 2>&1 | grep "guardrail"
```

### Resolution

This is **expected behavior** -- the guardrail system protects against strategy degradation. The strategy will auto-re-enable after `strategy_guardrails_disable_minutes` (default 120 minutes).

If you want to override:
1. Disable guardrails: `ai.strategy_guardrails_enabled: false` in config
2. Restart the bot
3. Re-enable guardrails after the strategy is re-tested

### Prevention
- Monitor strategy win rates and profit factors
- Use the auto-tuner to adjust weights based on performance
- Consider disabling consistently underperforming strategies permanently

---

## 10. Container Cannot Start (Port Conflict)

### Symptom
- `docker compose up` fails with "address already in use"
- Another service is using port 8090

### Diagnosis

```bash
# Check what's using the port
lsof -i :8090
# or
ss -tlnp | grep 8090
```

### Resolution

1. **Change host port** in `.env`:
   ```bash
   HOST_PORT=127.0.0.1:8091
   ```

2. **Stop conflicting service:**
   ```bash
   # If it's an old container
   docker rm -f <container_id>
   ```

3. **Restart:**
   ```bash
   docker compose up -d trading-bot
   ```

---

## 11. Live Mode Startup Failure

### Symptom
- Container crashes on startup in live mode
- Log: "DASHBOARD_ADMIN_KEY is required in live mode" or similar

### Diagnosis

```bash
docker logs novapulse --tail 50
```

### Resolution

Live mode requires all of the following:

```bash
# Required in .env
TRADING_MODE=live
DASHBOARD_ADMIN_KEY=<strong-random-key>
DASHBOARD_SESSION_SECRET=<strong-random-secret>
DASHBOARD_ADMIN_PASSWORD_HASH=<bcrypt-hash>
KRAKEN_API_KEY=<exchange-key>
KRAKEN_API_SECRET=<exchange-secret>
```

Generate a bcrypt hash:
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your_password', bcrypt.gensalt()).decode())"
```

### Prevention
- Always test in paper mode first
- Keep a checklist of required live-mode environment variables
- Use canary mode as an intermediate step

---

## 12. Elasticsearch Connection Failed

### Symptom
- Log: ES connection errors (non-blocking)
- ES indexes not being populated

### Diagnosis

```bash
# Check ES container
docker logs elasticsearch --tail 50

# Test ES health
curl -s http://localhost:9200/_cluster/health | python -m json.tool

# Check bot ES logs
docker logs novapulse 2>&1 | grep -i "elasticsearch\|es.*error"
```

### Resolution

ES failures are **non-blocking** -- the bot continues trading without ES analytics.

1. **ES container not running:**
   ```bash
   docker compose up -d elasticsearch
   ```

2. **ES out of memory:**
   - Check ES Java heap: default is 256MB
   - Increase if needed in docker-compose.yml: `ES_JAVA_OPTS=-Xms512m -Xmx512m`

3. **ES disk full:**
   ```bash
   # Check disk usage
   docker exec elasticsearch df -h /usr/share/elasticsearch/data

   # Delete old indexes
   curl -X DELETE "localhost:9200/novapulse-candles-*"
   ```

### Prevention
- ES is configured as a soft dependency (`required: false`)
- The bot starts even if ES is unavailable
- Index retention policies auto-delete old data
