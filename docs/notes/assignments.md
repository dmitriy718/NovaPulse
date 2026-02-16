# Notes: Assignments (Best-Effort)

These assignments are based on the current working tree and file timestamps, not commit authorship.

## Human (Dima)

1. `.env` (gitignored): user-stated change on 2026-02-12 (added Binance keys and new Coinbase key). Not inspected (secrets).

## Agentic (AI, core repo changes)

Tracked modified files:

1. `.env.example` (added `TRADING_EXCHANGES`)
1. `README.md` (Python version guidance)
1. `main.py` (multi-exchange boot path; Python 3.13 guard)
1. `pyproject.toml` (Python constraint)
1. `src/api/server.py` (tenant/auth hardening; multi-engine aggregation; control auth behavior)
1. `src/core/config.py` (shared env override helper; config loader with overrides)
1. `src/core/control_router.py` (tenant-scoped control actions)
1. `src/core/database.py` (tenant-scoped trade select in `close_trade`)
1. `src/core/engine.py` (optional dashboard; config override support)
1. `src/exchange/coinbase_rest.py` (trade history fallback)
1. `src/exchange/coinbase_ws.py` (additive subscriptions)
1. `src/exchange/market_data.py` (outlier reject returns `False`)
1. `src/utils/telegram.py` (tenant-aware reads and control calls)
1. `static/js/dashboard.js` (no hardcoded API key; runtime key requirement)
1. `tests/test_core.py` (new exchange/data + tenant/auth + guard tests)

Untracked additions (repo improvements/docs):

1. `.github/workflows/tests.yml` (CI for pytest on 3.11/3.12)
1. `src/core/multi_engine.py` (multi-engine hub/control helper)
1. `docs/kb-merged/` (canonical merged KB, 10 articles)
1. `docs/notes/FinalReview.md` (archived note)
1. `docs/notes/context2.txt` (archived note)

## Other Agent / Unknown

1. `knowledge_base/` (legacy KB tree; now superseded by `docs/kb-merged/`)

