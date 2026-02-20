# NovaPulse Live Pilot Runbook

This runbook is for a one-month solo live pilot with unattended windows up to 3-4 hours.

## 1. Scope and Guardrails

- Run in live mode with canary constraints first.
- Keep pair scope narrow (`BTC/USD`, `ETH/USD`) until stability is proven.
- Use hard runtime breakers:
  - stale data auto-pause
  - websocket disconnect auto-pause
  - consecutive-loss auto-pause
  - drawdown auto-pause
  - trade-rate throttle

## 2. One-Time Setup

### 2.1 Prepare environment file

```bash
cp .env.example .env
```

Set these values in `.env`:

- `TRADING_MODE=live`
- `ACTIVE_EXCHANGE=kraken` (or `coinbase`)
- `KRAKEN_API_KEY=...`
- `KRAKEN_API_SECRET=...`
- `START_PAUSED=true`
- `MAX_TRADES_PER_HOUR=8`
- `DASHBOARD_ADMIN_KEY=...`
- `DASHBOARD_SESSION_SECRET=...`
- `DASHBOARD_ADMIN_PASSWORD_HASH=...`
- `DASHBOARD_REQUIRE_API_KEY_FOR_READS=true`

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('replace_with_strong_password'))"
```

### 2.2 Confirm config guardrails

Check `config/config.yaml`:

- `trading.canary_mode: true`
- `trading.canary_pairs: ["BTC/USD", "ETH/USD"]`
- `trading.max_trades_per_hour: 8`
- `monitoring.auto_pause_on_stale_data: true`
- `monitoring.auto_pause_on_ws_disconnect: true`
- `monitoring.auto_pause_on_consecutive_losses: true`
- `monitoring.consecutive_losses_pause_threshold: 4`
- `monitoring.auto_pause_on_drawdown: true`
- `monitoring.drawdown_pause_pct: 8.0`

## 3. Preflight (Mandatory Before Every Live Start)

Run strict preflight:

```bash
python scripts/live_preflight.py --strict
```

Expected:

- exit code `0`
- no `FAILURES` block

If it fails, do not start live trading.

## 4. Start Procedure

### 4.1 Optional config snapshot before launch

```bash
python scripts/release_snapshot.py --label pre-live-start
```

### 4.2 Build and start

```bash
docker compose up -d --build
```

### 4.3 Verify health

```bash
curl -s http://127.0.0.1:8090/api/v1/health
curl -s -H "X-API-Key: $DASHBOARD_ADMIN_KEY" http://127.0.0.1:8090/api/v1/status
curl -s -H "X-API-Key: $DASHBOARD_ADMIN_KEY" http://127.0.0.1:8090/api/v1/risk
curl -s -H "X-API-Key: $DASHBOARD_ADMIN_KEY" http://127.0.0.1:8090/api/v1/performance
```

Confirm from `/api/v1/status`:

- `status: running`
- `canary_mode: true`
- `paused: true` (because `START_PAUSED=true`)
- `ws_connected: true`

### 4.4 Verify storage contract and ES target

SQLite is canonical; Elasticsearch is analytics mirror only.

```bash
curl -s -H "X-API-Key: $DASHBOARD_READ_KEY" http://127.0.0.1:8090/api/v1/storage
```

Confirm:

- `canonical_ledger: sqlite`
- `elasticsearch_role: analytics_mirror`
- every expected engine/account row appears with the correct `db_path_abs`
- `es_target` matches your intended runtime sink (`cloud` or `hosts`)

If `docker compose` local Elasticsearch is running while `es_target=cloud`, that local service is not your active analytics sink.

### 4.5 Resume trading when checks are good

```bash
curl -s -X POST \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY" \
  http://127.0.0.1:8090/api/v1/control/resume
```

## 5. Unattended 3-4 Hour Window Checklist

Before leaving:

1. `/api/v1/status`: `running`, `paused=false`, `ws_connected=true`.
2. `/api/v1/scanner`: no widespread stale pairs.
3. `/api/v1/risk`:
   - drawdown below your pause threshold
   - open positions count acceptable
4. `/api/v1/execution`: order flow is normal (no abnormal spike in placed orders).
5. `docker compose logs --tail=200 trading-bot` has no repeating error loops.

During unattended window (recommended every 30-60 min remote check):

```bash
curl -s -H "X-API-Key: $DASHBOARD_ADMIN_KEY" http://127.0.0.1:8090/api/v1/status
curl -s -H "X-API-Key: $DASHBOARD_ADMIN_KEY" http://127.0.0.1:8090/api/v1/risk
```

Watch for:

- `paused=true`
- non-empty `auto_pause_reason`

## 6. Emergency Controls

Pause immediately:

```bash
curl -s -X POST \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY" \
  http://127.0.0.1:8090/api/v1/control/pause
```

Flatten all open positions:

```bash
curl -s -X POST \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY" \
  http://127.0.0.1:8090/api/v1/control/close_all
```

Resume only after root cause is understood:

```bash
curl -s -X POST \
  -H "X-API-Key: $DASHBOARD_ADMIN_KEY" \
  http://127.0.0.1:8090/api/v1/control/resume
```

## 7. Daily Operating Routine

1. Pre-start strict preflight.
2. Snapshot config:
   ```bash
   python scripts/release_snapshot.py --label daily-start
   ```
3. Start paused, verify status/risk, then resume.
4. End of day:
   - export/check trades and risk
   - capture logs if anomalies:
     ```bash
     docker compose logs --since=24h trading-bot > logs/daily-$(date +%F).log
     ```

## 8. Rollback Procedure

Rollback config to latest snapshot:

```bash
python scripts/release_rollback.py --latest
docker compose restart trading-bot
```

Rollback to a specific snapshot:

```bash
python scripts/release_rollback.py --snapshot-id <snapshot_id>
docker compose restart trading-bot
```

## 9. Canary Expansion Plan (Month Pilot)

Only expand after at least 7 stable days with no unresolved auto-pauses.

Sequence:

1. Increase canary pair count by 1.
2. Keep same risk caps for 3-5 days.
3. Re-evaluate logs + risk metrics.
4. Repeat.

Do not disable canary mode during the first month unless stability is consistently demonstrated.

## 10. Useful Commands

Follow logs:

```bash
docker compose logs -f trading-bot
```

Container status:

```bash
docker compose ps
```

Health script:

```bash
bash scripts/health_check.sh
```

Run walk-forward gate manually:

```bash
python scripts/walk_forward_gate.py
```
