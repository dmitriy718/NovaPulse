# NovaPulse Operations Guide

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Docker Deployment

### Architecture

NovaPulse runs as a Docker container managed by docker-compose:

```
Host Machine
    |
    +-- docker-compose.yml
    |     |
    |     +-- trading-bot (container: novapulse)
    |     |     Port: 8090 (host) -> 8080 (container)
    |     |     Volumes: ./data, ./logs, ./models, ./config, ./.secrets
    |     |     Resources: 2GB RAM limit, 2 CPUs
    |     |     Restart: unless-stopped
    |     |
    |     +-- elasticsearch (optional)
    |     |     Port: 127.0.0.1:9200
    |     |     Volume: es-data (named)
    |     |
    |     +-- kibana (debug profile only)
    |           Port: 127.0.0.1:5601
    |
    +-- .env (secrets, port overrides)
    +-- config/config.yaml (trading config, read-only mount)
    +-- data/ (SQLite DBs, instance lock)
    +-- logs/ (structlog output)
    +-- models/ (TFLite model artifacts)
    +-- .secrets/ (Telegram secrets)
```

### Common Commands

#### Build and Start
```bash
docker compose up -d --build trading-bot
```

#### Rebuild After Config Change
```bash
# Config changes (config/config.yaml): just restart, no rebuild needed
docker compose restart trading-bot

# Code changes: rebuild
docker compose up -d --build trading-bot
```

#### View Logs
```bash
# Last 100 lines
docker logs novapulse --tail 100

# Follow live
docker logs novapulse --tail 50 -f

# Since a specific time
docker logs novapulse --since "2026-02-22T10:00:00"
```

#### Stop
```bash
docker compose stop trading-bot

# Stop everything including ES
docker compose down
```

#### Run DB Queries Against Live Container
```bash
docker exec novapulse python -c "
import asyncio, json
from src.core.database import DatabaseManager
async def main():
    db = DatabaseManager('/app/data/trading.db')
    await db.initialize()
    stats = await db.get_performance_stats()
    print(json.dumps(stats, indent=2))
asyncio.run(main())
"
```

#### Check Container Health
```bash
# Docker health status
docker inspect novapulse --format='{{.State.Health.Status}}'

# API health endpoint (no auth required)
curl -s http://localhost:8090/api/v1/health | python -m json.tool
```

#### Resource Usage
```bash
docker stats novapulse --no-stream
```

### Environment Variables

All secrets and port overrides are in `.env`:

```bash
# Required for live mode
TRADING_MODE=paper
KRAKEN_API_KEY=your_key
KRAKEN_API_SECRET=your_secret
DASHBOARD_ADMIN_KEY=your_admin_key
DASHBOARD_SESSION_SECRET=your_session_secret
DASHBOARD_ADMIN_PASSWORD_HASH=$2b$12$...

# Optional
HOST_PORT=127.0.0.1:8090
DASHBOARD_PORT=8080
BOT_UID=1000
BOT_GID=1000
LOG_LEVEL=INFO
```

### Bind Mount Permissions

The container runs as `BOT_UID:BOT_GID` (default 1000:1000). Ensure the host directories are writable:

```bash
chown -R 1000:1000 data/ logs/ models/
```

---

## Mode Transitions

### Paper to Live

1. Verify sufficient trade history in paper mode (50+ trades recommended)
2. Set exchange API credentials in `.env`
3. Set required live-mode secrets:
   ```bash
   TRADING_MODE=live
   DASHBOARD_ADMIN_KEY=<strong-random-key>
   DASHBOARD_SESSION_SECRET=<strong-random-secret>
   DASHBOARD_ADMIN_PASSWORD_HASH=<bcrypt-hash>
   ```
4. Consider starting in canary mode first:
   ```bash
   CANARY_MODE=true
   CANARY_PAIRS=BTC/USD
   CANARY_MAX_POSITION_USD=100
   CANARY_MAX_RISK_PER_TRADE=0.005
   ```
5. Rebuild and restart:
   ```bash
   docker compose up -d --build trading-bot
   ```
6. Monitor for 24 hours before expanding to full pair set

### Live to Paper

1. Close all positions first:
   ```bash
   curl -X POST http://localhost:8090/api/v1/control/close_all \
     -H "X-API-Key: $DASHBOARD_ADMIN_KEY"
   ```
2. Change `TRADING_MODE=paper` in `.env`
3. Restart: `docker compose restart trading-bot`

### Canary to Full

1. Verify canary mode performance
2. Remove or set `CANARY_MODE=false` in `.env`
3. Restart: `docker compose restart trading-bot`

---

## Log Inspection

### Structlog JSON Format

All logs are structured JSON:

```json
{
  "event": "Trade executed",
  "trade_id": "T-abc123def456",
  "pair": "BTC/USD",
  "side": "buy",
  "price": 65432.10,
  "size_usd": 450.00,
  "mode": "paper",
  "level": "info",
  "logger": "executor",
  "timestamp": "2026-02-22T14:30:00.123456Z"
}
```

### Finding Specific Events

```bash
# All trade executions
docker logs novapulse 2>&1 | grep '"event": "Trade executed"'

# All errors
docker logs novapulse 2>&1 | grep '"level": "error"'

# Strategy timeouts
docker logs novapulse 2>&1 | grep '"event": "Strategy timed out"'

# Risk blocks
docker logs novapulse 2>&1 | grep '"event": "Trade blocked"'

# Stop-outs
docker logs novapulse 2>&1 | grep '"reason": "stop_loss"'

# Exchange errors
docker logs novapulse 2>&1 | grep -i "exchange.*error"
```

### Log Rotation

Docker log rotation is configured in docker-compose.yml:
- Max size: 50MB per file
- Max files: 5
- Driver: json-file

Application logs are also written to `logs/` directory on disk.

---

## Database Operations

### Direct SQLite Access

```bash
# From host (if data/ is a bind mount)
sqlite3 data/trading.db

# From inside container
docker exec -it novapulse sqlite3 /app/data/trading.db
```

### Common Queries

```sql
-- Recent trades
SELECT trade_id, pair, side, entry_price, exit_price, pnl, status, strategy
FROM trades
ORDER BY created_at DESC
LIMIT 20;

-- Open positions
SELECT trade_id, pair, side, entry_price, stop_loss, take_profit, quantity
FROM trades
WHERE status = 'open';

-- Strategy performance
SELECT strategy,
       COUNT(*) as trades,
       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
       ROUND(AVG(pnl), 2) as avg_pnl,
       ROUND(SUM(pnl), 2) as total_pnl
FROM trades
WHERE status = 'closed'
GROUP BY strategy
ORDER BY total_pnl DESC;

-- Daily P&L
SELECT DATE(exit_time) as day,
       COUNT(*) as trades,
       ROUND(SUM(pnl), 2) as daily_pnl
FROM trades
WHERE status = 'closed'
GROUP BY day
ORDER BY day DESC;

-- Recent thoughts (AI decision log)
SELECT timestamp, category, message, severity
FROM thought_log
ORDER BY id DESC
LIMIT 20;
```

### WAL Mode Verification

```sql
PRAGMA journal_mode;  -- Should return "wal"
PRAGMA synchronous;   -- Should return "1" (NORMAL)
```

### Instance Lock

The file `data/instance.lock` prevents duplicate bot processes. If the bot fails to start with "instance lock" error:

1. Verify no other bot is running: `docker ps | grep novapulse`
2. If no other bot is running, delete the lock: `rm data/instance.lock`
3. Restart: `docker compose restart trading-bot`

---

## Dashboard API

### Authentication

All endpoints except `/api/v1/health` require authentication:

```bash
# Using admin key (full access)
curl http://localhost:8090/api/v1/status \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"

# Using read key (read-only)
curl http://localhost:8090/api/v1/trades \
  -H "X-API-Key: $DASHBOARD_READ_KEY"
```

### Key Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/health` | None | Health check (for Docker/LB probes) |
| GET | `/api/v1/status` | Read | System status, uptime, mode |
| GET | `/api/v1/trades` | Read | Trade history with filters |
| GET | `/api/v1/positions` | Read | Open positions with current prices |
| GET | `/api/v1/performance` | Read | Win rate, P&L stats, Sharpe ratio |
| GET | `/api/v1/strategies` | Read | Per-strategy performance stats |
| GET | `/api/v1/risk` | Read | Risk report (bankroll, drawdown, exposure) |
| GET | `/api/v1/thoughts` | Read | AI thought feed |
| GET | `/api/v1/scanner` | Read | Latest market scanner results |
| POST | `/api/v1/control/pause` | Admin | Pause trading |
| POST | `/api/v1/control/resume` | Admin | Resume trading |
| POST | `/api/v1/control/close_all` | Admin | Emergency close all positions |
| POST | `/api/v1/control/kill` | Admin | Close all + stop engine |
| WS | `/ws/live` | Query param | Real-time WebSocket stream |
| POST | `/api/v1/login` | Session | Web UI login |

### Control Commands via API

```bash
# Pause trading
curl -X POST http://localhost:8090/api/v1/control/pause \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"

# Resume trading
curl -X POST http://localhost:8090/api/v1/control/resume \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"

# Close all positions
curl -X POST http://localhost:8090/api/v1/control/close_all \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"

# Emergency kill (close all + stop)
curl -X POST http://localhost:8090/api/v1/control/kill \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY"
```

### Control via Telegram / Discord / Slack

All three bots support the same commands through the ControlRouter:
- `/status` - System status
- `/pnl` - Performance and P&L
- `/positions` - Open positions
- `/pause` - Pause trading
- `/resume` - Resume trading
- `/close_all` - Close all positions

---

## Elasticsearch (Optional)

### Setup

ES is optional and runs as a sidecar container. Enable in config:

```yaml
elasticsearch:
  enabled: true
  hosts: ["http://elasticsearch:9200"]
```

Or via environment: `ELASTICSEARCH_ENABLED=true`

### ES Indexes

| Index | Data | Retention |
|-------|------|-----------|
| `novapulse-candles` | OHLCV candle data | 90 days |
| `novapulse-orderbook` | Order book snapshots | 30 days |
| `novapulse-sentiment` | Fear/Greed, news sentiment | 180 days |
| `novapulse-onchain` | On-chain metrics | 180 days |
| `novapulse-market` | CoinGecko market data | 180 days |
| `novapulse-trades` | Trade lifecycle events (mirror) | 365 days |

**Important:** SQLite is the canonical ledger. ES is a mirror for analytics only.

### Kibana

Start Kibana for visualization (debug profile):

```bash
docker compose --profile debug up -d kibana
```

Access at http://localhost:5601

---

## Monitoring Checklist

### Daily

- [ ] Check dashboard for open positions and P&L
- [ ] Verify WebSocket is connected (status endpoint)
- [ ] Review any error-level log entries
- [ ] Check daily trade count vs expectations

### Weekly

- [ ] Review strategy performance (strategies endpoint)
- [ ] Check risk report (bankroll, drawdown, exposure)
- [ ] Review auto-tuner changes (if enabled)
- [ ] Check container resource usage (`docker stats`)
- [ ] Verify DB size is reasonable

### Monthly

- [ ] Review overall P&L trend
- [ ] Check for any disabled strategies (guardrails)
- [ ] Verify log rotation is working
- [ ] Review ES index sizes (if enabled)
- [ ] Consider updating ML model (retrain)
