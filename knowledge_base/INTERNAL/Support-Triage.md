# NovaPulse Support Triage

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## What To Collect First

Before triaging any issue, collect the following:

1. **Container status:** `docker ps -a | grep novapulse`
2. **Recent logs (last 200 lines):** `docker logs novapulse --tail 200`
3. **System status:** `curl -s http://localhost:8090/api/v1/status -H "X-API-Key: $KEY"`
4. **Risk report:** `curl -s http://localhost:8090/api/v1/risk -H "X-API-Key: $KEY"`
5. **Trading mode:** paper or live
6. **Time of incident:** UTC timestamp
7. **Customer tenant_id** (if multi-tenant)

---

## Priority Levels

### P0 - Critical (Respond: Immediately)

**Impact:** Financial loss risk, data corruption, security breach

| Scenario | Actions |
|----------|---------|
| Live mode: exit order failed after 3 retries | 1. Check exchange UI for open position. 2. Close manually. 3. Update DB. 4. Investigate logs for root cause. |
| Exchange API key compromised | 1. Disable key on exchange immediately. 2. Rotate key (see Credential-Rotation.md). 3. Review trade history for unauthorized activity. |
| Bot executing trades in wrong mode | 1. Kill bot: `curl -X POST .../control/kill`. 2. Verify TRADING_MODE in .env. 3. Restart with correct mode. |
| Database corruption | 1. Stop bot. 2. Check integrity: `sqlite3 data/trading.db "PRAGMA integrity_check"`. 3. Restore from backup. |
| Container in restart loop (OOM kill) | 1. `docker inspect novapulse --format='{{.State.OOMKilled}}'`. 2. Increase memory limit. 3. Restart. |

### P1 - High (Respond: Within 1 Hour)

**Impact:** Trading capability degraded but no immediate financial risk

| Scenario | Actions |
|----------|---------|
| WebSocket disconnected > 10 minutes | 1. Check network connectivity. 2. Check Kraken status page. 3. Restart container. 4. If circuit breaker paused, resume after WS reconnects. |
| All strategies guardrail-disabled | 1. Check strategy stats API. 2. Review recent trade performance. 3. Consider temporarily disabling guardrails. 4. Restart bot. |
| Daily loss limit reached (unexpected) | 1. Review trades that caused losses. 2. Check for rapid consecutive losses. 3. Wait for midnight UTC reset. 4. Consider increasing daily loss limit if trades were valid. |
| Dashboard unreachable (port/auth) | 1. Check container health. 2. Verify port binding. 3. Verify API key matches .env. |
| Telegram/Discord/Slack bot not responding | 1. Check bot token validity. 2. Check logs for auth errors. 3. Verify chat IDs are correct. 4. Restart container. |

### P2 - Medium (Respond: Within 4 Hours)

**Impact:** Degraded functionality but bot is operating normally

| Scenario | Actions |
|----------|---------|
| ML model not loading | Non-blocking. Bot trades without AI confidence. Check models/ directory and file permissions. |
| ES pipeline failures | Non-blocking. Analytics data not being collected. Check ES container health. |
| Strategy consistently underperforming | Review strategy stats. Consider manual weight adjustment. Wait for auto-tuner cycle. |
| Position reconciliation warnings | Review ghost/orphan reports. Check exchange UI. Usually informational. |
| High memory usage (approaching limit) | Monitor trend. Reduce data retention. Consider increasing limit. |

### P3 - Low (Respond: Next Business Day)

**Impact:** Cosmetic or informational issues

| Scenario | Actions |
|----------|---------|
| Log noise (non-critical warnings) | Review and adjust log level if needed. |
| Dashboard refresh slow | Check DB query performance. Consider reducing thought_feed_max. |
| Config validation warnings | Review warnings, update config if needed. |
| Stale ML features (no recent trades) | Expected in quiet markets. Features will update when trades resume. |

---

## Triage Decision Tree

```
Is the bot running?
  |
  +-- NO --> Is the container healthy?
  |            |
  |            +-- Container restarting --> Check logs, see Runbook #1
  |            +-- Container stopped --> Start it: docker compose up -d
  |
  +-- YES --> Is it trading?
               |
               +-- NO --> Is it paused?
               |           |
               |           +-- YES --> See Runbook #3 (Trading Paused)
               |           +-- NO --> Check risk report, see below
               |
               +-- YES --> Is there a specific issue?
                           |
                           +-- Wrong trades --> Check mode (paper/live)
                           +-- No fills --> Check exchange connectivity
                           +-- Losses --> Review strategy performance
```

### Not Trading But Not Paused

If the bot is running and not paused but not trading, check:

1. **Bankroll depleted?** Risk report shows `bankroll <= 0`
2. **Global cooldown?** After a loss, 30-min cooldown is default
3. **All positions full?** `open_positions >= max_concurrent_positions`
4. **Quiet hours?** Check if current UTC hour is in `quiet_hours_utc`
5. **No signals?** Market may be flat. Check scanner results.
6. **Data stale?** WS may be disconnected. Check `ws_connected`.
7. **All strategies disabled?** Check strategy stats for `runtime_disabled`.

---

## Multi-Tenant Support Triage

For multi-tenant deployments:

### Tenant Cannot Access API

1. Verify tenant API key is valid: check `tenant_api_keys` table in DB
2. Verify tenant status is "active" or "trialing": check `tenants` table
3. Verify tenant_id matches the key mapping
4. Check if `require_api_key_for_reads` is enabled (should be for multi-tenant)

### Tenant Data Isolation

All data tables include a `tenant_id` column. Verify queries are scoped:

```sql
-- Check tenant's trades
SELECT * FROM trades WHERE tenant_id = '<tenant_id>' ORDER BY created_at DESC LIMIT 10;

-- Check tenant status
SELECT * FROM tenants WHERE tenant_id = '<tenant_id>';
```

### Billing Issues

If Stripe billing is enabled:

1. Check `stripe_webhook_events` table for recent webhook deliveries
2. Verify `STRIPE_WEBHOOK_SECRET` matches the Stripe dashboard
3. Check tenant subscription status in Stripe dashboard
4. Verify `billing.stripe.price_id_pro` and `billing.stripe.price_id_premium` are correct

---

## Escalation Path

| Level | Who | When |
|-------|-----|------|
| L1 | On-call support | First response, follow runbooks |
| L2 | Senior engineer | Runbook doesn't resolve, needs code investigation |
| L3 | Core developer | Data corruption, security incident, critical bug |

---

## Communication Templates

### Customer: "Bot Is Not Trading"

> We've checked your NovaPulse instance and found [REASON]. [EXPLANATION].
>
> **Action taken:** [ACTION]
>
> **Expected resolution:** [TIMELINE]
>
> If you need immediate assistance, you can [pause/resume] trading via the dashboard or Telegram bot.

### Customer: "I'm Losing Money"

> We understand your concern. Trading involves risk, and past performance does not guarantee future results. Let us review your instance:
>
> - **Strategy performance:** [SUMMARY]
> - **Risk settings:** max_risk_per_trade=[X]%, max_daily_loss=[Y]%
> - **Circuit breakers:** [STATUS]
>
> **Recommendations:**
> 1. Consider reducing `max_risk_per_trade` if losses are too large per trade
> 2. Consider enabling `canary_mode` for controlled exposure
> 3. Review the risk management documentation for optimal settings

### Internal: P0 Incident

> **P0 INCIDENT: [TITLE]**
>
> **Time:** [UTC TIMESTAMP]
> **Tenant:** [TENANT_ID or "all"]
> **Mode:** [paper/live]
> **Impact:** [DESCRIPTION]
>
> **Actions taken:**
> 1. [ACTION 1]
> 2. [ACTION 2]
>
> **Root cause:** [CAUSE or "Under investigation"]
> **Status:** [Resolved/Investigating/Mitigated]
