# Final Comprehensive Code Review

**Date:** 2026-02-05  
**Scope:** Full codebase post prior reviews — deep dive across all systems  
**Categorization:** By afflicted system/component

---

## Deployment Follow-Up (2026-02-14)

This section captures issues found while validating two live-ish deployments (Horizon main host + Raspberry Pi test host), plus the concrete fixes applied.

### DPLY1 (Medium): Telegram health check script could silently fail (fixed)

**Where:** `scripts/health_check.sh` (Raspberry Pi deployment repo had the same script).  
**Problem:** The script used `set -euo pipefail` and attempted to find the bot PID via:

- `pgrep -fa "venv/bin/python main.py" | awk ...`

This pattern does **not** match common process commandlines like:

- `/home/dima/ai-trade/venv/bin/python /home/dima/ai-trade/main.py`

Under `pipefail`, a “no match” exit code from `pgrep` caused the script to terminate early (no “DOWN” alert, no check-in).  

**Fix:** Updated PID discovery to be resilient and to avoid terminating under `pipefail`, with:

1. Prefer Docker container presence (`ai-trading-bot`) when running under compose.
1. Fallback to a robust `pgrep` regex (`venv/bin/python.*main\.py`) wrapped so “no match” does not abort the script.

**Status:** Fixed locally in this repo and copied into the Raspberry Pi deployment so the existing cron `*/30` check-ins actually run.

### DPLY2 (Low): Raspberry Pi docker-compose could not start due to port collision (triaged)

**Where:** Raspberry Pi test host.  
**Problem:** `docker compose up` failed because host port `8080` was already bound by an existing long-running process:

- `/home/dima/ai-trade/venv/bin/python /home/dima/ai-trade/main.py`

**Resolution:** Removed the created (non-started) docker container, left the existing running bot process in place, and relied on the cron-based check-ins + error watcher to report health.  
**Follow-up recommendation:** If Docker is the intended supervisor, move the host process into a systemd unit or stop it before starting compose, and set `DASHBOARD_PORT` to a non-conflicting port.

### DPLY3 (Medium): Horizon main deploy lacked Telegram check-ins (fixed)

**Where:** `ops@165.245.143.68` (`/home/ops/agent-stack`).  
**Problem:** No cron check-ins existed, and the stack did not have Telegram secrets configured.  
**Fix:** Added:

1. `/home/ops/agent-stack/.secrets/telegram_token` + `telegram_chat_id` (permissions 600).
1. `/home/ops/agent-stack/ops/health_check.sh`: sends a 30-minute “Horizon Check-in” to Telegram based on Docker container state/health.
1. Crontab entry: `*/30 * * * * /home/ops/agent-stack/ops/health_check.sh`.

**Status:** Installed and executed successfully; writes a local log to `/home/ops/agent-stack/ops_notes/health_check.log`.

---

## Deployment Follow-Up (2026-02-15)

This section captures issues found while re-validating the ops-host Docker deployment after additional hardening and Telegram changes.

### DPLY4 (High): Ops `ai-trading-bot` container marked unhealthy due to healthcheck 403 (fixed)

**Where:** Ops host `/home/ops/aitradercursor2` Docker deployment.  
**Problem:** Docker healthchecks were probing `/api/v1/status`, but that endpoint returns `403` when `dashboard.require_api_key_for_reads: true` (by design). This caused the container to remain `unhealthy` even though the service was functioning.  
**Fix:** Switched Dockerfile + `docker-compose.yml` healthchecks to probe `/api/v1/health` (intentionally public and excluded from rate limiting).  
**Status:** Fixed locally; requires redeploy to ops.

### DPLY5 (High): Telegram `409 Conflict` due to multi-deploy polling of same bot token (fixed)

**Where:** Ops container logs (python-telegram-bot).  
**Problem:** `getUpdates` long polling cannot run in parallel across multiple deployments for a single bot token, causing Telegram `409 Conflict: terminated by other getUpdates request`.  
**Fix:** Added config `control.telegram.polling_enabled` (default `false`) and changed Telegram polling default to send-only unless explicitly enabled (or overridden with `TELEGRAM_POLLING_ENABLED`).  
**Status:** Fixed locally; requires redeploy to ops (and should be kept disabled on all but one deployment per bot token).

### DPLY6 (Medium): Ops cron health check script failed under Docker mode (fixed)

**Where:** `scripts/health_check.sh` (ops host running bot in Docker).  
**Problem:** Two issues caused non-zero exits (no log written, no Telegram message):
1. When the bot runs in Docker, the script marks `pid=0` (container present). The embedded Python printed an empty uptime field, which collapsed shell field parsing and could break subsequent numeric formatting.
1. Ops shells (and cron) did not export `HOSTNAME`, and `set -u` made `${HOSTNAME}` an unbound-variable fatal error.
**Fix:** Python snippet now always prints a numeric uptime (`0.0` when no host PID is available), and the script now uses `${HOSTNAME:-$(hostname)}` for the host label.  
**Status:** Fixed locally; requires syncing the updated script to ops (and pi, since both use this script path).

## Local Hardening Follow-Up (2026-02-14)

This section captures local codebase fixes applied after validating deployments, focused on making the dashboard/control plane safer and aligning runtime constraints with real deployments.

### HARD1 (High): Python 3.13 support mismatch (fixed)

**Problem:** `main.py` hard-exited on Python 3.13, while the repo was being tested and deployed on Python 3.13.x. `pyproject.toml` also claimed `<3.13`.

**Fix:** Updated runtime guard and metadata:

1. `main.py` now rejects Python `3.14+` (not `3.13+`).
1. `pyproject.toml` now declares `requires-python = ">=3.11,<3.14"`.
1. Updated unit test accordingly.

**Status:** Verified via local `pytest` run.

### HARD2 (Critical): Unauthenticated reads/WS defaulted to `default` tenant (fixed)

**Problem:** Dashboard read endpoints and `/ws/live` could resolve to the `default` tenant without credentials if the API was reachable, which is unsafe for any internet-exposed deployment.

**Fix:** Added a secure-by-default switch and enforced it:

1. New config field: `dashboard.require_api_key_for_reads` (default `true`).
1. `resolve_tenant_id(..., require_api_key=True)` now fails closed (401/403) instead of falling back to `default`.
1. Read endpoints and `/ws/live` enforce the above when the config flag is enabled.
1. `static/js/dashboard.js` now passes `api_key` on the WebSocket URL and sends `X-API-Key` on read fetches that the UI performs.

**Status:** Verified via unit tests (strict auth behavior) and local `pytest` run.

### HARD3 (Medium): Vault cryptography documentation mismatch (fixed)

**Problem:** `src/core/vault.py` claimed "AES-256" but uses `cryptography.fernet.Fernet` (AES-128-CBC + HMAC).

**Fix:**

1. Corrected module/class docs to reflect Fernet + PBKDF2 reality.
1. Implemented checksum verification on load (the envelope already stored a checksum but it wasn't being enforced).
1. Added a unit test to ensure corrupted vault envelopes are rejected.

**Status:** Verified via local `pytest` run.

### HARD4 (Medium): ML normalization leakage in training pipeline (fixed)

**Problem:** `src/ml/trainer.py` normalized features using mean/std computed on the full dataset prior to splitting, which leaks validation-set statistics into training.

**Fix:**

1. `ModelTrainer._prepare_data()` now splits first, fits normalization on the train split only, and applies it to both train/val.
1. Training now receives pre-split data in the subprocess to ensure evaluation uses the same split used for normalization.
1. Updated unit tests to match the new return shape and to avoid assuming a fixed row order.

**Status:** Verified via local `pytest` run.

### HARD5 (High): Control-plane key scoping (implemented)

**Problem:** Allowing tenant API keys to execute control actions (pause/resume/close_all) increases blast radius if a read-only key is leaked.

**Fix:** Added `dashboard.allow_tenant_keys_for_control` (default `false`). When false, control endpoints accept only `DASHBOARD_SECRET_KEY`; when true, tenant keys are accepted as before.

**Status:** Implemented and covered by local `pytest` run (existing suite).

### HARD6 (High): Built-in Telegram check-ins every 30 minutes (implemented)

**Problem:** Deployments relied on external cron scripts for periodic Telegram check-ins, which can silently fail and are not portable across environments.

**Fix:** Implemented a first-class check-in loop:

1. Added `control.telegram.send_checkins` and `control.telegram.checkin_interval_minutes` to config.
1. `TelegramBot` now supports a `checkin_loop()` that sends periodic operational summaries while the engine is running.
1. `main.py` starts the check-in loop alongside Telegram polling (single-engine mode; and only once in multi-exchange mode).

**Status:** Verified via unit test + local `pytest` run.

### HARD7 (Medium): CSV export endpoint + dashboard download button (implemented)

**What:** Added `/api/v1/export/trades.csv` (tenant-scoped, auth-protected when reads require a key) and a dashboard button to download the file.

**Why:** Operators and paying users typically expect auditability: exporting trades to spreadsheets / accounting / third-party analytics without DB access.

**Status:** Verified via unit test + local `pytest` run.

### HARD8 (High): API security headers + rate limiting (implemented)

**What:** Added:

1. Default security headers (CSP, nosniff, frame deny, etc.) and `Cache-Control: no-store` for `/api/*` responses.
1. In-memory token-bucket rate limiting per client IP (configurable in `dashboard.*`).

**Why:** This is required if the dashboard ever leaves a trusted LAN; it reduces accidental exposure and simple abuse/DoS.

**Status:** Verified via unit tests + local `pytest` run.

### HARD9 (High): Live safety circuit breakers (implemented)

**What:** Added simple auto-pause guardrails in `src/core/engine.py`:

1. Auto-pause after N consecutive stale-data health checks (`monitoring.auto_pause_on_stale_data`).
1. Auto-pause after sustained WS disconnect duration (`monitoring.auto_pause_on_ws_disconnect`).

Both actions log an audit thought and (if enabled) send a Telegram alert.

**Why:** For unattended live trading, the worst failures are running blind (stale feed, disconnected WS) and continuing to act. Safe-stop should be automatic.

**Status:** Verified via unit tests + local `pytest` run.

## 1. TRADE EXECUTION

### 1.1 Executor (`src/execution/executor.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | E1 | `_close_position` log_thought uses wrong tenant | When closing via `close_all_positions(tenant_id=X)` for a different tenant, `log_thought` still uses `tenant_id=self.tenant_id` instead of `tid`. Thoughts appear under wrong tenant in dashboard. |
| **Low** | E2 | `update_bar` returns `None` on outlier reject | `market_data.update_bar` returns without value when outlier is rejected (line 175); effectively returns `None`. Callers treat truthy/falsy; works but semantically unclear. |
| **Low** | E3 | Live close uses market order only | Closes always use market orders; no option for limit close to reduce slippage on TP exits. |
| **Low** | E4 | `_fill_from_trade_history` lookback fixed at 7200s | 2-hour lookback may miss fills for orders placed >2h ago. |

### 1.2 Risk Manager (`src/execution/risk_manager.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | R1 | `_trade_history` unbounded growth then truncation | History truncated to 5000 when >10000; 10k trades = ~80KB. Consider periodic pruning or capped deque. |
| **Low** | R2 | `calculate_risk_of_ruin` returns 0 for <50 trades | Correct design; document that RoR is disabled until sufficient history. |

---

## 2. EXCHANGE / MARKET DATA

### 2.1 Market Data Cache (`src/exchange/market_data.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | M1 | `update_bar` outlier rejection returns implicitly | Line 175: `return` without value on outlier reject; returns `None`. Function declares `-> bool`. Should explicitly `return False`. |
| **Low** | M2 | 20% outlier threshold may reject legitimate moves | Crypto can move >20% in minutes; legitimate bars may be dropped. Consider configurable threshold. |
| **Low** | M3 | Direct `_data` access on RingBuffer | `_buffers[pair][col]._data[idx]` bypasses encapsulation; couples MarketDataCache to RingBuffer internals. |
| **Low** | M4 | `get_spread` returns 0 for empty book | No distinction between "no data" and "zero spread"; callers may misinterpret. |

### 2.2 Kraken REST (`src/exchange/kraken_rest.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | K1 | `get_order_info` / `get_closed_orders` may differ by exchange | Kraken vs Coinbase response shapes; executor assumes Kraken format. Coinbase client has separate implementation. |
| **Low** | K2 | No explicit connection timeout on `aiosqlite` | Database uses `timeout=30`; exchange client uses httpx timeout. Already acceptable. |

### 2.3 Coinbase REST/WS (`src/exchange/coinbase_rest.py`, `coinbase_ws.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | C1 | Symbol format may differ | Kraken uses `XXBTZUSD`; Coinbase uses `BTC-USD`. Ensure pair mapping is consistent in engine. |
| **Low** | C2 | Sandbox market data limitations | Documented; user must set `COINBASE_MARKET_DATA_URL` for production data in sandbox. |

---

## 3. AI / SIGNAL GENERATION

### 3.1 Confluence Detector (`src/ai/confluence.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | CF1 | Staleness check depends on `market_data.is_stale` | S3 fix applied; ensure WS disconnect triggers staleness. |
| **Low** | CF2 | Strategy list hardcoded | New strategies require code changes to confluence. |
| **Low** | CF3 | `record_trade_result` callback may throw | Executor catches exceptions; ensure no side effects on failure. |

### 3.2 Predictor (`src/ai/predictor.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | P1 | Model path may not exist | `load_model` handles missing file; returns `is_model_loaded=False`. Acceptable. |
| **Low** | P2 | `_cache_key` and non-serializable values | M27 fix; ensure state dicts don't contain numpy arrays. |

### 3.3 Strategies (base, keltner, trend, etc.)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | S1 | `_sanitize_for_json` NaN/Inf | M20: base strategy should handle NaN/Inf in metadata. |
| **Low** | S2 | Reversal candlestick patterns | H4: uses `closes` as `opens` fallback; pattern detection may be weak. |
| **Low** | S3 | Momentum "consecutive" counting | M21: documentation says "consecutive" but logic may count total. |

---

## 4. DATABASE

### 4.1 Database Manager (`src/core/database.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | D1 | `get_open_trades` tenant filter `tenant_id=? OR tenant_id IS NULL` | Legacy rows with NULL tenant_id included; acceptable for migration. |
| **Low** | D2 | Metrics timestamp format | Python `datetime.now().isoformat()` vs SQLite `datetime('now')`; ensure queries use correct format. |
| **Low** | D3 | No connection pool | Single connection; OK for typical load. Consider pool for high concurrency. |
| **Low** | D4 | `cleanup_old_data` doesn't touch trades | Only metrics, thought_log, order_book_snapshots; trades retained indefinitely. By design for audit. |

---

## 5. CONFIG / VAULT

### 5.1 Config Manager (`src/core/config.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | CF1 | Env mappings for `initial_bankroll` and `db_path` | M3: `INITIAL_BANKROLL` maps to `risk.initial_bankroll`; `DB_PATH` maps to `app.db_path`. Both exist in models. Verify mapping keys. |
| **Low** | CF2 | Strategy weights not validated to sum to 1.0 | L1: weights used for confluence; no strict sum validation. |
| **Low** | CF3 | `ConfigManager.__init__` called on every `get_config()` | Singleton `__new__` runs once; `__init__` may run again. Check for double-load. |

### 5.2 Vault (`src/core/vault.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | V1 | Docstring says AES-256; Fernet uses AES-128 | M11: Fernet is AES-128-CBC; docstring misleading. |
| **Low** | V2 | Checksum written but never verified | M8: integrity check on load would improve security. |
| **Low** | V3 | Salt not cached between init and save | M9: if file deleted between init and first save, could fail. |

---

## 6. API / SERVER

### 6.1 Dashboard Server (`src/api/server.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | A1 | `_require_auth` vs `_resolve_tenant_id` | Control endpoints use `X-API-Key` as dashboard secret. Tenant resolution uses same header for `get_tenant_id_by_api_key`. If dashboard secret != tenant API key, tenant falls back to default. Document intended usage. |
| **Low** | A2 | CORS restricted to localhost | H12 fix; production may need configurable origins. |
| **Low** | A3 | WebSocket cache per tenant | H13 fix; 1s cache reduces N+1. Cache invalidation on control actions (pause/resume) not explicit. |
| **Low** | A4 | `get_tenant` endpoint unauthenticated | `/api/v1/tenants/{tenant_id}` returns tenant info; consider auth for sensitive data. |
| **Low** | A5 | Stripe webhook has no rate limit | Webhook signature verified; consider rate limiting for DoS. |

---

## 7. UI/UX

### 7.1 Dashboard JavaScript (`static/js/dashboard.js`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Critical** | U1 | Hardcoded `API_KEY` | Line 323: `const API_KEY = 'change_this_to_a_random_string'` — default is insecure. Users must override. Document prominently. |
| **Medium** | U2 | No XSS sanitization on thought messages | `escHtml` used for category and message; ensure all user-facing content is escaped. |
| **Low** | U3 | Strategy stats poll every 5s | Fetch when server reachable; acceptable. |
| **Low** | U4 | No loading state for pause/close_all | Buttons have no disabled state during request; user could double-click. |
| **Low** | U5 | `formatMoneyPlain` for negative shows positive | `Math.abs(n)` in formatMoneyPlain; negative equity displays as positive. Verify intent. |

### 7.2 Dashboard HTML/CSS (`static/index.html`, `static/css/dashboard.css`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | U6 | External font dependency | Google Fonts; consider self-hosting for offline/resilience. |
| **Low** | U7 | No CSP headers | Content Security Policy not set; reduces XSS mitigation. |

---

## 8. SECONDARY SYSTEMS

### 8.1 Telegram Bot (`src/utils/telegram.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | T1 | Chat ID allowlist | C5 fix: `chat_ids` config restricts commands. Verify `_is_authorized` used on all sensitive commands. |
| **Low** | T2 | `get_open_trades` without tenant_id | Line 283: `positions = await self._bot_engine.db.get_open_trades()` — no tenant_id. Single-tenant default; multi-tenant would need tenant awareness. |
| **Low** | T3 | `close_all` / `kill` use executor directly | Bypass control_router when available; engine uses single tenant. |

### 8.2 Billing (Stripe) (`src/billing/stripe_service.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | B1 | Webhook idempotency | Stripe may retry; ensure handlers are idempotent. |
| **Low** | B2 | Price ID and currency config | Verify `price_id` matches `currency` in Stripe dashboard. |

### 8.3 Discord / Slack (`src/utils/discord_bot.py`, `slack_bot.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | D1 | Chat ID / channel verification | Ensure same auth pattern as Telegram for Discord/Slack. |

---

## 9. ML / BACKTESTING

### 9.1 Backtester (`src/ml/backtester.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | BT1 | Equal votes default to SHORT | L16: `long_votes > short_votes` else SHORT; tie breaks to short. Document or make configurable. |
| **Low** | BT2 | Sharpe annualization assumes 1-min bars | L17: May overstate for infrequent trading. |
| **Low** | BT3 | NumPy slicing creates views | `closes[:i+1]` returns view; no O(n²) copy. H14 may be non-issue for NumPy. |
| **Low** | BT4 | No seed parameter in `run()` | `param_tune.py` has `--seed`; backtester `run()` doesn't accept seed for reproducibility. |

### 9.2 Trainer (`src/ml/trainer.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Medium** | TR1 | Training in subprocess | H10 fix: `_run_training_process` isolates TensorFlow; event loop not blocked. |
| **Low** | TR2 | Data leakage in normalization | H9: If normalization uses full dataset before split, leakage. `_prepare_data` should split first. |
| **Low** | TR3 | Feature ordering | H11: Ensure consistent key order in feature vector. |

---

## 10. MAIN / INFRASTRUCTURE

### 10.1 Main Entry (`main.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | MA1 | `preflight_checks` always returns True on success | L4 fix: returns False when .env missing; still allows run for paper mode. |
| **Low** | MA2 | Signal handlers on Windows | `loop.add_signal_handler` may not work on Windows; consider `signal.signal` fallback. |
| **Low** | MA3 | Server shutdown timeout 5s | May be short for large state; consider configurable. |

### 10.2 Engine (`src/core/engine.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | EN1 | `_collect_scan_pairs` queue logic | `get_nowait` in loop may raise QueueEmpty; caught by outer try. Verify pair deduplication. |
| **Low** | EN2 | Health monitor WS restart | S9 fix: WS task restart logic; `_reconnect_count` reset. |
| **Low** | EN3 | Coinbase REST candle poll | Bar format `[time, o, h, l, c, vwap, volume, count]`; verify column order matches Kraken. |

### 10.3 Logger (`src/core/logger.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | L1 | RotatingFileHandler | M7 fix applied; 50MB main, 10MB errors. |
| **Low** | L2 | Root logger handlers cleared | Avoids duplicate handlers on repeated setup. |

---

## 11. CONTROL ROUTER

### 11.1 Control Router (`src/core/control_router.py`)

| Severity | ID | Issue | Description |
|----------|-----|-------|-------------|
| **Low** | CR1 | `close_all` tenant_id passed through | Implemented; `kill()` does not accept tenant_id (closes all for engine). |
| **Low** | CR2 | `get_positions` uses engine tenant_id | Single-tenant; multi-tenant API would need tenant parameter. |

---

## 12. SUMMARY BY SEVERITY

| Severity | Count | Notable |
|----------|-------|---------|
| **Critical** | 1 | U1: Hardcoded API key in dashboard.js |
| **Medium** | 6 | E1 tenant log, M1 update_bar return, V1 vault docstring, A1 auth/tenant, U2 XSS, T1 Telegram auth |
| **Low** | 45+ | Various robustness, docs, config, edge cases |

---

## 13. RECOMMENDED PRIORITIES

1. **Immediate:** Remove or document hardcoded `API_KEY` in dashboard.js; require env/config.
2. **Short-term:** Fix E1 (log_thought tenant_id in _close_position), M1 (update_bar return False).
3. **Medium-term:** Document auth/tenant flow for API; add tenant_id to Telegram get_open_trades if multi-tenant.
4. **Long-term:** Vault checksum verification; configurable CORS; CSP headers; seed in backtester run().

---

## 14. FIXES ALREADY APPLIED (from prior reviews)

- ConfigManager thread-safety (M1)
- Env var conversion logging (M2)
- Database tenant scoping (update_trade, close_trade)
- Executor tenant_id pass-through
- Control router close_all tenant_id
- API server tenant_id for close_all
- Dashboard ephemeral secret logging
- Risk manager daily PnL check (C3)
- Executor retry on live close (C6)
- Executor entry+exit fees in PnL (C7)
- Logger RotatingFileHandler (M7)
- S1–S17 (Second Review)
- Numerous First Review items (C1–C7, H1–H16, etc.)
