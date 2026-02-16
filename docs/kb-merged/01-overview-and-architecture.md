# Overview and Architecture

## One-Sentence Summary

An AI-powered crypto trading system that ingests market data, generates signals, sizes risk, executes orders, persists state, and exposes a dashboard and control surface for operators.

## What Exists In This Repo

Core capabilities:

1. Exchange adapters (Kraken/Coinbase)
1. Market data cache (prices/bars/spread/staleness)
1. Strategy layer + multi-strategy confluence
1. Optional ML predictor + trainer + backtester
1. Execution engine (paper/live)
1. Risk manager and safety guards
1. Dashboard API + UI + WebSocket live feed
1. Optional Telegram control plane
1. Optional billing/tenancy plumbing (Stripe + tenant API keys)

Entry points:

1. Local bot entry: `main.py`
1. Engine: `src/core/engine.py` (`BotEngine`)
1. Dashboard server: `src/api/server.py` (`DashboardServer`)

## High-Level Data Flow

1. Market data arrives via exchange WebSocket and/or REST candles.
1. `MarketDataCache` stores bars/prices and tracks data freshness.
1. Strategies compute candidate signals from recent bars and microstructure.
1. Confluence aggregates signals across strategies and timeframes.
1. Risk manager sizes trades and enforces guardrails (daily loss, max risk, staleness, etc).
1. Executor places/cancels orders, watches fills, and manages open positions.
1. State is persisted to SQLite (trades, thought log, metrics, tenants).
1. Dashboard surfaces status/performance/positions/thoughts and exposes authenticated controls.

## Runtime Loops (Local Bot)

Typical long-running loops (names vary):

1. Scan loop (entries)
1. Position loop (stop/exit management)
1. WS data loop (market feed maintenance)
1. Health monitor (reconnect/guard behavior)
1. Cleanup loop (periodic maintenance)
1. Optional Coinbase REST candle poll loop (candles/backfill)
1. Optional Telegram loop

## Multi-Exchange Mode (Optional)

The bot can run multiple `BotEngine` instances in one process and present a unified dashboard/control surface.

Configuration:

1. Single exchange: `ACTIVE_EXCHANGE=kraken` (or `EXCHANGE_NAME`)
1. Multi exchange: `TRADING_EXCHANGES=kraken,coinbase`

Implementation:

1. Multi-engine helpers: `src/core/multi_engine.py`
1. Multi-mode startup: `main.py`

## Where Things Live (Map)

1. Config: `src/core/config.py`, `config/config.yaml`, `.env`, `.env.example`
1. Engine: `src/core/engine.py`
1. Control router: `src/core/control_router.py`
1. DB manager: `src/core/database.py`
1. Exchange:
   - Coinbase: `src/exchange/coinbase_ws.py`, `src/exchange/coinbase_rest.py`
   - Kraken: `src/exchange/kraken_ws.py`, `src/exchange/kraken_rest.py` (if present)
1. Market cache: `src/exchange/market_data.py`
1. Strategies: `src/strategies/`
1. Confluence: `src/ai/confluence.py`
1. ML: `src/ml/`
1. Execution: `src/execution/`
1. API/UI:
   - FastAPI: `src/api/server.py`
   - UI: `static/`
1. Telegram: `src/utils/telegram.py`
1. Billing: `src/billing/stripe_service.py`

## Key Invariants (Support/Dev)

1. Safety over activity: stale feed and risk guards are expected to block entries.
1. Auth is mandatory for control: pause/resume/close_all/settings writes require `X-API-Key`.
1. Tenant safety: a tenant API key cannot control or read other tenants.
1. Python constraint: use Python 3.11 or 3.12; Python 3.13 is blocked by guard rails.

## Managed Deployment Stack (Environment-Specific)

Some deployments include a containerized stack behind a reverse proxy with Basic Auth and optional "agent" service. Those details are deployment-specific and should be treated as separate from the local bot.

If you operate such a stack, see:

1. Operations: `docs/kb-merged/10-troubleshooting-operations-release.md`
1. Security: `docs/kb-merged/09-billing-tenancy-security.md`

