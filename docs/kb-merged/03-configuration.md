# Configuration (YAML + Env + Secrets)

## Sources of Config

1. YAML: `config/config.yaml`
1. Environment overrides: `.env` (template: `.env.example`)
1. Loader/validation: `src/core/config.py`

Operational rule:

1. Environment variables override YAML for selected high-impact keys.

## Common YAML Settings (Support/Dev Reference)

App:

1. `app.mode`: `paper` or `live`
1. `app.db_path`: SQLite DB path

Exchange:

1. `exchange.name`: `kraken` or `coinbase`
1. `exchange.rest_url`, `exchange.ws_url`
1. `exchange.maker_fee`, `exchange.taker_fee`
1. `exchange.post_only`
1. `exchange.limit_chase_attempts`
1. `exchange.limit_fallback_to_market`

Trading:

1. `trading.pairs`
1. `trading.scan_interval_seconds`
1. `trading.position_check_interval_seconds`
1. `trading.timeframes`
1. `trading.max_spread_pct`
1. `trading.use_closed_candles_only`
1. `trading.strategy_cooldowns_seconds`
1. `trading.single_strategy_mode`
1. `trading.candle_poll_seconds` (if used)

AI:

1. `ai.confluence_threshold`
1. `ai.min_confidence`
1. `ai.obi_counts_as_confluence`
1. `ai.book_score_max_age_seconds`
1. `ai.multi_timeframe_min_agreement`
1. `ai.primary_timeframe`

Risk:

1. `risk.max_risk_per_trade`
1. `risk.max_daily_loss`
1. `risk.max_position_usd`
1. `risk.kelly_fraction`
1. `risk.max_kelly_size`
1. `risk.risk_of_ruin_threshold`
1. `risk.global_cooldown_seconds_on_loss`

Control:

1. `control.telegram.token`
1. `control.telegram.chat_ids` (allowlist)
1. `control.web.enabled`

Billing:

1. `billing.stripe.enabled`
1. `billing.tenant.default_tenant_id`

## Recommended Workflow (Client)

1. Change only one knob at a time.
1. Run in paper mode after each change.
1. Watch the dashboard thought log for "why" decisions (stale feed, spread, risk block).

## High-Impact Knobs (What To Tune First)

Trade frequency:

1. `ai.confluence_threshold`
1. `ai.min_confidence`
1. `ai.obi_counts_as_confluence`

Market hygiene:

1. `trading.max_spread_pct`
1. `trading.use_closed_candles_only`

Risk:

1. `risk.max_risk_per_trade`
1. `risk.max_daily_loss`
1. `risk.max_position_usd`

## Exchange Selection (Single vs Multi)

Single:

1. `ACTIVE_EXCHANGE=kraken` or `EXCHANGE_NAME=kraken`

Multi:

1. `TRADING_EXCHANGES=kraken,coinbase`

Implementation:

1. Startup: `main.py`
1. Exchange parsing + DB path shaping: `src/core/multi_engine.py`

DB note:

1. If you share a DB across engines, you should expect aggregated reads to be consistent but trade rows may need an `exchange` label to disambiguate.
1. If you separate DBs per exchange, aggregation must fan-out across engines.

## Control Keys and UI Key Handling

Admin control key:

1. `DASHBOARD_ADMIN_KEY`

UI behavior:

1. The dashboard UI does not ship a hardcoded control key.
1. It reads a runtime key from:
   - `localStorage.DASHBOARD_API_KEY`, or
   - `window.DASHBOARD_API_KEY`

File:

1. `static/js/dashboard.js`

## Environment Overrides (Support/Dev Reference)

Common keys (see `.env.example` for full list):

1. `TRADING_MODE`
1. `LOG_LEVEL`
1. `DB_PATH`
1. `DASHBOARD_HOST`
1. `DASHBOARD_PORT`
1. `ACTIVE_EXCHANGE`
1. `TRADING_EXCHANGES`

## Managed Stack Configuration (Environment-Specific)

If you run a container stack on a server, there may be additional configuration sources such as:

1. Host env file (secrets): `/home/ops/agent-stack/.env`
1. Compose file: `/home/ops/agent-stack/docker-compose.yml`
1. Reverse proxy config: `/home/ops/agent-stack/Caddyfile`

These are deployment-specific and should be access-controlled (operator-only).

## Secrets Hygiene

1. Never commit `.env`.
1. Treat exchange keys and control keys as production secrets.
1. Rotate keys when:
   - a device is lost
   - credentials are shared
   - access should be revoked
