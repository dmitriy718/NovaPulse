# Support Triage (Internal)

Goal: reduce turnaround time by collecting the right data up front.

## Intake template (copy/paste)

1. Deployment:
- Mode: paper/live
- Exchange: kraken/coinbase
- Multi-exchange enabled: yes/no
- Python version:

2. Config:
- `config/config.yaml` diffs (or key fields: pairs, timeframes, confluence_threshold, min_confidence, max_spread_pct)
- `.env` redacted (confirm `DASHBOARD_ADMIN_KEY` is set in live mode)

3. Symptoms:
- What is wrong (no trades / too many trades / stale / fills failing / dashboard not updating)
- When it started (timestamp UTC)
- Affected pairs

4. Evidence:
- `GET /api/v1/status`
- `GET /api/v1/scanner`
- `GET /api/v1/risk`
- Relevant log excerpt from `logs/errors.log`

## Common issue map

No trades:
- Confluence too strict: `ai.confluence_threshold`, `ai.min_confidence`
- Spread filter too strict: `trading.max_spread_pct`
- Data stale: `scanner.stale=true`
- Tenant inactive (billing): API returns 403 `Tenant inactive`

Dashboard controls fail:
- Missing `X-API-Key` header
- Browser missing `DASHBOARD_API_KEY` localStorage entry

Positions not closing:
- Live order fill/partial fill issues; check `_wait_for_fill` behavior and exchange order state.

## Escalation rules

Escalate to engineering when:
- Cross-tenant data/control concerns appear.
- Order placement fails repeatedly with valid balances/permissions.
- WS reconnect loops exceed configured thresholds.
