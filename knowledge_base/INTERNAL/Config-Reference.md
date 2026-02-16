# Configuration Reference (Internal)

Last updated: 2026-02-13

## Files

1. Environment file (secrets): `/home/ops/agent-stack/.env`
1. Compose file: `/home/ops/agent-stack/docker-compose.yml`
1. Caddy routing + auth: `/home/ops/agent-stack/Caddyfile`

## Agent API (`agent-api`)

Key env vars:

1. `ANTHROPIC_API_KEY`: required.
1. `ANTHROPIC_MODEL`: optional, defaults to `claude-opus-4-6` in code.
1. `AGENT_NAME`: defaults to `HorizonOperator`.
1. `QDRANT_URL`: set to `http://qdrant:6333` in compose.

Endpoints:

1. `GET /health`
1. `POST /chat` with JSON `{ "query": "...", "scenario_id": <optional>, "context": <optional object> }`

## Market Engine (`market`)

The market engine reads configuration from environment variables. Values are set via:

1. `env_file: .env` (secrets + exchange credentials).
1. explicit `environment:` values in compose (tuning parameters).

Important operational flags:

1. `TRADING_ENABLED`: `1` or `0`.
1. `COINBASE_SANDBOX_ENABLED`: `1` uses sandbox base URL.
1. `KRAKEN_TRADING_ENABLED`: `1` enables real Kraken order placement (should remain `0` unless explicitly authorized).
1. `EMERGENCY_STOP_FILE`: kill switch file path.
1. `PAUSE_FILE`: pause file path.

Risk and sizing constraints:

1. `INITIAL_CASH_USD`
1. `MAX_DAILY_LOSS_USD`
1. `MAX_TOTAL_EXPOSURE_USD`
1. `MAX_POSITION_USD`
1. `MAX_ORDER_USD`
1. `MIN_ORDER_USD`

Staleness guardrails:

1. `STALE_FEED_SECS`
1. `STALE_BOOK_SECS`
1. `STALE_STARTUP_GRACE_SECS`

Execution guardrails:

1. `MAX_SPREAD_BPS`
1. `COOLDOWN_SECS`

## Nova Horizon API

The market engine exposes HTTP on `DASHBOARD_PORT` (default 9000) with routes:

1. `GET /api/health`
1. `GET /api/state`
1. `GET /api/trades`
1. `POST /api/kill`
1. `POST /api/pause`
1. `POST /api/resume`

## Caddy Auth Model

1. `agent.horizonsvc.com` protects only `/chat` with Basic Auth user `agent`.
1. `nova.horizonsvc.com` protects all paths with Basic Auth user `nova`.

Passwords are stored as plaintext in files for operator access:

1. `/home/ops/agent-stack/.agent_chat_pass`
1. `/home/ops/agent-stack/.nova_pass`

Hashes are stored separately:

1. `/home/ops/agent-stack/.agent_chat_hash`
1. `/home/ops/agent-stack/.nova_hash`
