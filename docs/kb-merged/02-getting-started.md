# Getting Started (Local + Managed)

## Audience

1. Clients: use "Managed Access" if you were given hosted URLs, otherwise use "Local Run".
1. Support/Dev: use the "Validation Checklist" and "First-Run Debug" sections.

## Local Run (Developer or Self-Hosted)

### Prereqs

1. Python 3.11 or 3.12
1. A unix-like shell (macOS/Linux recommended)

### Run Steps

1. Create `.env`:
   - Start from `.env.example` and fill required values.
1. Create venv and install deps:
   - `python3.11 -m venv venv`
   - `source venv/bin/activate`
   - `pip install -r requirements.txt`
1. Start:
   - `python main.py`
1. Open:
   - `http://localhost:8080`

### Paper vs Live

1. Paper mode simulates orders/fills.
1. Live mode places real orders and should require:
   - exchange credentials
   - a control key set (`DASHBOARD_SECRET_KEY`)

## Managed Access (Client)

If support gave you hosted endpoints:

1. Dashboard: open the provided URL and authenticate (often Basic Auth).
1. Optional agent endpoint:
   - `GET /health`
   - `POST /chat` (authenticated)

If you see `401 Unauthorized`, your credentials are wrong or expired.

Client-side fixes to try:

1. Open the dashboard in an incognito window.
1. Close all tabs for the domain and reopen.
1. Clear saved site credentials for the domain (browser settings).

If it still fails, contact support and include your time window. See:

1. `docs/kb-merged/10-troubleshooting-operations-release.md`

## Validation Checklist (Support/Dev)

Local bot API:

1. `GET /api/v1/status`
1. `GET /api/v1/scanner` and confirm most pairs are `stale: false`
1. WebSocket:
   - connect to `/ws/live`

Control:

1. `POST /api/v1/control/pause` with header `X-API-Key: <admin or tenant key>`
1. `POST /api/v1/control/resume` with header `X-API-Key: <admin or tenant key>`

## First-Run Debug (Support/Dev)

1. Confirm Python version:
   - use 3.11/3.12 only
1. Confirm DB is writable:
   - default `data/trading.db` or `DB_PATH`
1. Confirm exchange selection:
   - `ACTIVE_EXCHANGE` or `TRADING_EXCHANGES`
1. Watch logs:
   - `logs/trading_bot.log`
   - `logs/errors.log`
