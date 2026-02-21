# Dashboard and Controls

## What The Dashboard Shows (Client)

Typical panels:

1. Status (running/paused, WS connected, mode)
1. Performance (PnL, win rate, trades)
1. Positions (open trades, unrealized PnL)
1. Thought log (why the bot acted or did not act)
1. Scanner (price/bars/staleness)

If you see widespread staleness, do not resume trading until it clears.

## Dashboard Walkthrough (Client, Managed UI Variant)

Some deployments use a "status pill" summary. Common meanings:

1. `LIVE`: engine is running and not blocked by safeguards
1. `PAUSED`: paused by an operator
1. `STOPPED`: emergency stop engaged
1. `STALE FEED`: market data is stale; trading is intentionally blocked
1. `OFFLINE`: UI cannot reach the API

Common metrics:

1. Equity: estimated total value (cash + positions at current price)
1. Cash: available cash not in positions
1. Realized PnL: profit/loss from closed trades (often shown "today")
1. Unrealized PnL: profit/loss on currently open positions
1. Exposure: notional value allocated into open positions

Signals:

1. BUY: system is biased toward entering or adding
1. SELL: system is biased toward reducing
1. HOLD: no action indicated

Confidence is a relative score and does not guarantee profitability.

## Core API Endpoints (Support/Dev)

Reads:

1. `GET /api/v1/status`
1. `GET /api/v1/scanner`
1. `GET /api/v1/performance`
1. `GET /api/v1/positions`
1. `GET /api/v1/trades`
1. `GET /api/v1/thoughts`
1. `GET /api/v1/execution`

WebSocket:

1. `/ws/live`

Implementation:

1. `src/api/server.py`

## Controls and Auth

Control endpoints:

1. `POST /api/v1/control/pause`
1. `POST /api/v1/control/resume`
1. `POST /api/v1/control/close_all`

Auth header:

1. `X-API-Key: <key>`

Valid keys:

1. Admin key: `DASHBOARD_ADMIN_KEY`
1. Tenant API keys: keys mapped to a tenant id (tenant-pinned)

Tenant-safe behavior:

1. A tenant key cannot act on another tenant.
1. If a tenant is inactive, non-admin access is denied.

## "Buttons Do Nothing" (Client)

Common causes:

1. Control key is not configured in the UI runtime.
1. Credentials are wrong or have expired (managed deployments).

UI key requirement (local bot dashboard UI):

1. Set `localStorage.DASHBOARD_API_KEY` to the provided key, then refresh.
1. Alternatively set `window.DASHBOARD_API_KEY` before the dashboard JS loads (deployment-specific).

## Settings

Settings endpoints:

1. `GET /api/v1/settings`
1. `PATCH /api/v1/settings` (auth required)

Example:

1. Weighted Order Book toggle (`weighted_order_book`)

## Multi-Exchange Notes (Client + Support)

1. Some responses may include an `exchange` field when aggregating multiple engines.
1. Status may show an `exchanges` array with per-engine WS and paused state.
