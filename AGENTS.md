# NovaPulse Development Guide

## Cursor Cloud specific instructions

### Overview

NovaPulse is a Python 3.12 AI-powered algorithmic trading bot with a FastAPI dashboard. It uses SQLite (embedded, no server needed) as its canonical ledger. External services (Kraken, Coinbase, Elasticsearch, Telegram, etc.) are optional and degrade gracefully when unavailable.

### Running the application

The app runs locally without Docker:

```bash
source venv/bin/activate
PYTHONPATH=/workspace TRADING_EXCHANGES=kraken DASHBOARD_REQUIRE_API_KEY_FOR_READS=false python main.py
```

**Critical**: The `config/config.yaml` has `trading_exchanges` set to a multi-exchange value (kraken + coinbase). Without overriding `TRADING_EXCHANGES=kraken`, the bot tries to initialize Coinbase which requires a private key and will crash. Always set `TRADING_EXCHANGES=kraken` for local dev unless you have Coinbase credentials.

Dashboard is served at `http://localhost:8080` (static HTML/CSS/JS in `/workspace/static/`).

### Running tests

```bash
source venv/bin/activate
PYTHONPATH=/workspace python -m pytest tests/ -v --tb=short
```

All tests use in-memory stubs (no real DB or external services needed). There are 4 pre-existing test failures (`test_login_brute_force.py` x3, `test_stocks_env_aliases.py` x1).

### Linting

```bash
source venv/bin/activate
ruff check .          # fast linter (72 pre-existing warnings)
python -m mypy src/   # type checker (299 pre-existing errors, mostly union-attr)
```

### Key gotchas

- The `.env` file is created from `.env.example` but requires `TRADING_EXCHANGES=kraken` override for single-exchange local dev.
- `DASHBOARD_REQUIRE_API_KEY_FOR_READS=false` must be set to access the dashboard and API without authentication keys.
- The instance lock at `data/instance.lock` must be removed if the previous process didn't shut down cleanly: `rm -f data/instance.lock`.
- TFLite model is optional; the bot falls back to heuristic prediction when `models/trade_predictor.tflite` is absent.
- The Stock Scanner (Polygon/Alpaca) initializes but returns $0 prices when API keys are absent — this is expected in dev.
