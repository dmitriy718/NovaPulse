# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

NovaPulse v4.5.0 — an AI-powered algorithmic trading system (Python 3.11–3.13). Single monolithic process running a FastAPI dashboard on port 8080. See `README.md` for full feature list and architecture.

### Development setup

- **Python venv**: `python3 -m venv venv && source venv/bin/activate`
- **Install deps**: see the update script or CI workflow for the pip install commands. CI uses the Pi/ARM requirements file (no TensorFlow), not the full x86 requirements file.
- **Env file**: `cp .env.example .env` — then adjust values as needed. Paper mode is default and safe.

### Running the application

The `.env.example` ships with `TRADING_EXCHANGES` set to multi-exchange mode (kraken + coinbase). To run locally without Coinbase API keys, override to single exchange:

```bash
TRADING_EXCHANGES=kraken python main.py
```

The dashboard is served on `http://127.0.0.1:8080`. The bot starts in paper mode by default.

**Gotcha — injected secrets override `.env`**: In Cloud Agent VMs, secrets like `DASHBOARD_ADMIN_KEY`, `DASHBOARD_READ_KEY`, and `TRADING_EXCHANGES` are injected as system env vars. `python-dotenv`'s `load_dotenv()` does NOT override existing env vars. To use a custom value, set it as an explicit env var in the shell command (e.g. `TRADING_EXCHANGES=kraken python main.py`).

### Tests

```bash
source venv/bin/activate
python -m pytest -q
```

- 171 tests pass; 4 pre-existing failures in `test_login_brute_force.py` (3) and `test_stocks_env_aliases.py` (1) — not caused by environment setup.
- CI workflow (`.github/workflows/tests.yml`) uses `requirements-pi.txt` on Python 3.11 and 3.12.
- pytest config is in `pyproject.toml` (`asyncio_mode = "auto"`).

### Linting

```bash
ruff check .   # linter (config in pyproject.toml, line-length=100)
mypy .         # type checker (ignore_missing_imports=true)
```

### Key directories

| Path | Description |
|------|-------------|
| `src/` | Application source (14 subpackages) |
| `tests/` | Test suite (32 files + conftest.py) |
| `config/config.yaml` | Master configuration (484 lines) |
| `scripts/` | Ops scripts (health, watchdog, preflight, release) |
| `data/` | SQLite databases (created at runtime) |
| `models/` | ML model artifacts |
| `logs/` | Runtime logs |

### API interaction

Control endpoints require the admin API key via `X-API-Key` header. In Cloud Agent VMs, use the injected `DASHBOARD_ADMIN_KEY` env var (don't hardcode — it's a secret). Example:

```python
import os, httpx
key = os.environ['DASHBOARD_ADMIN_KEY']
httpx.post('http://127.0.0.1:8080/api/v1/control/pause', headers={'X-API-Key': key})
```

Read endpoints: when `DASHBOARD_REQUIRE_API_KEY_FOR_READS=false`, no auth is needed for GET endpoints.
