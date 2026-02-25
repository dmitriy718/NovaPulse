# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

NovaPulse v4.5.0 is an AI crypto/stock trading bot. Single Python application (`main.py`) with a FastAPI dashboard, SQLite (embedded) canonical DB, and optional Elasticsearch analytics mirror.

### Running the application locally (without Docker)

```bash
source venv/bin/activate
APP_ENV=development \
ACTIVE_EXCHANGE=kraken \
TRADING_EXCHANGES="" \
TRADING_ACCOUNTS="" \
TRADING_MODE=paper \
START_PAUSED=true \
DASHBOARD_ADMIN_PASSWORD=devpass123 \
DASHBOARD_ADMIN_PASSWORD_HASH="" \
DASHBOARD_REQUIRE_API_KEY_FOR_READS=false \
DASHBOARD_HOST=0.0.0.0 \
DASHBOARD_PORT=8080 \
python main.py
```

Dashboard at `http://127.0.0.1:8080` — login with `admin` / `devpass123`.

### Key gotchas

- **Injected secrets override**: The Cloud Agent VM injects secrets (e.g. `DASHBOARD_ADMIN_PASSWORD_HASH`) that override `.env` values. To use plaintext dev password, you must explicitly set `DASHBOARD_ADMIN_PASSWORD_HASH=""` as an env var to clear the injected hash.
- **APP_ENV**: The `.env` file defaults to `APP_ENV=production`, which blocks plaintext password login. Override with `APP_ENV=development` for local dev.
- **Multi-exchange crash**: If `TRADING_EXCHANGES` or `TRADING_ACCOUNTS` resolves to multiple exchanges (e.g. Coinbase), the bot will crash without valid Coinbase private keys. Set `TRADING_EXCHANGES=""` and `TRADING_ACCOUNTS=""` to run Kraken-only in paper mode.
- **Instance lock**: The bot uses a file-based single-instance lock. If you kill the process without cleanup, remove lock files: `rm -f /tmp/novapulse_instance.lock data/*.lock`.

### Lint, test, build

- **Lint**: `ruff check .` (configured in `pyproject.toml`, line-length=100)
- **Type check**: `mypy src/ --ignore-missing-imports`
- **Tests**: `python -m pytest tests/ -v` (171/175 pass; 4 pre-existing failures)
- **No build step**: Pure Python, runs directly via `python main.py`

### Project structure

See `README.md` for architecture diagram. Key paths:
- `main.py` — entry point
- `src/` — all source modules (14 subdirectories)
- `config/config.yaml` — master configuration
- `tests/` — pytest test suite
- `static/` — dashboard frontend (HTML/CSS/JS)
