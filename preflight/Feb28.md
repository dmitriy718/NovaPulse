# NovaPulse v5.0.0 — Comprehensive Code Review
**Date:** 2026-02-28
**Scope:** Full codebase audit of all modified files. Four user-reported issues investigated.

## What Was Reviewed

All files shown in `git diff` (staged and unstaged), with deep dives into:
- `src/core/engine.py`
- `src/execution/executor.py`
- `src/execution/risk_manager.py`
- `src/core/control_router.py`
- `src/core/multi_engine.py`
- `src/api/server.py`
- `src/core/database.py`
- `config/config.yaml`
- `static/js/dashboard.js`

---

## CRITICAL Issues

### CRITICAL-1: `close_reason` not in `TRADE_UPDATE_COLUMNS` — ghost reconciliation crashes every cycle

**Confidence: 100**

**Files:**
- `src/execution/executor.py:344`
- `src/core/database.py:635-639`

```python
# executor.py:340-344
await self.db.update_trade(trade_id, {
    "status": "closed",
    "exit_price": entry_price,
    "pnl": 0.0,
    "close_reason": "ghost_reconciliation",   # ValueError raised here
})
```

`database.py:656` raises `ValueError: Column 'close_reason' not allowed in trade updates` because `"close_reason"` is not in `TRADE_UPDATE_COLUMNS`:

```python
# database.py:635-639
TRADE_UPDATE_COLUMNS = frozenset({
    "exit_price", "pnl", "pnl_pct", "fees", "slippage", "status",
    "stop_loss", "take_profit", "trailing_stop", "exit_time",
    "duration_seconds", "notes", "metadata", "quantity",
})
```

The `trades` table has no `close_reason` column — close reasons are stored in `metadata` JSON. The exception is caught at executor.py line 348, so the bot continues running, but the ghost position is never closed and the reconciliation error repeats every 5 minutes indefinitely.

**Fix:** Change `"close_reason"` to `"notes"` at executor.py line 344:

```python
await self.db.update_trade(trade_id, {
    "status": "closed",
    "exit_price": entry_price,
    "pnl": 0.0,
    "notes": "ghost_reconciliation",
})
```

---

### CRITICAL-2: CSV export returns HTTP 400 in multi-engine mode — broken for current deployment

**Confidence: 97**

**File:** `src/api/server.py:1662-1663`

```python
if not self._engines_share_db(engines):
    raise HTTPException(status_code=400, detail="CSV export requires a shared DB")
```

```python
# server.py:288-294
def _engines_share_db(self, engines: List[Any]) -> bool:
    paths = []
    for e in engines:
        db = getattr(e, "db", None)
        if db and getattr(db, "db_path", None):
            paths.append(db.db_path)
    return len(set(paths)) <= 1
```

The current deployment runs three engines with three separate databases (`trading_kraken_default.db`, `trading_coinbase_default.db`, `trading_stocks_default.db`). `_engines_share_db` returns `False`, causing HTTP 400 on every CSV download attempt. The dashboard JS at `static/js/dashboard.js:1760` correctly calls `/api/v1/export/trades.csv` but the server rejects it before reaching the actual export logic. This is the root cause of the broken CSV link.

**Fix:** Replace the hard fail with aggregation across all engine DBs:

```python
# In export_trades_csv handler — replace lines 1659-1668 with:
engines = self._get_engines()
if not engines:
    raise HTTPException(status_code=503, detail="Bot not running")

all_rows = []
for eng in engines:
    if getattr(eng, "db", None):
        try:
            rows = await eng.db.get_trade_history(
                limit=limit, tenant_id=tenant_id
            )
            all_rows.extend(rows)
        except Exception:
            pass

all_rows.sort(
    key=lambda r: r.get("exit_time") or r.get("entry_time") or "",
    reverse=True,
)
all_rows = all_rows[:limit]
rows = all_rows
```

---

### CRITICAL-3: Resume does not prevent immediate re-trigger of consecutive-losses circuit breaker

**Confidence: 90**

**Files:**
- `src/core/engine.py:211-256` (`_apply_circuit_breakers`)
- `src/core/control_router.py:85-107` (`resume`)

The resume flow works correctly: `ControlRouter.resume()` sets `_trading_paused = False`, `_auto_pause_reason = ""`, and `rm._consecutive_losses = 0`. However, `_apply_circuit_breakers` runs in `_health_monitor` every 30 seconds (config: `health_check_interval: 30`). After resume:

1. `_consecutive_losses` is reset to 0
2. The health monitor fires within 0–30 seconds
3. The health monitor calls `risk_manager.get_risk_report()` which reads `_consecutive_losses`
4. If `_consecutive_losses` is still 0, the circuit breaker does not re-trigger

But there is no grace period preventing re-triggering. After resume, the next 5 losing trades (at the 48h challenge's `consecutive_losses_pause_threshold: 5`) will re-trigger the auto-pause. If the bot is in a losing streak (as reported — all recent trades are losses), this means:

- Resume → 5 more losses → auto-pause again (in as little as 5 × 20s cooldown = ~100 seconds)
- The user resumes again → same thing
- Oscillation continues indefinitely

**Fix:** Add `_auto_pause_cooldown_until: float = 0.0` to `BotEngine.__init__()` and set it in `ControlRouter.resume()`:

```python
# In ControlRouter.resume() — after clearing _trading_paused:
if hasattr(self._engine, "_auto_pause_cooldown_until"):
    self._engine._auto_pause_cooldown_until = time.time() + 300  # 5-min grace

# In BotEngine._apply_circuit_breakers() — consecutive loss check:
if getattr(self, "_auto_pause_cooldown_until", 0.0) > time.time():
    pass  # Grace period: don't re-trigger consecutive loss breaker
elif losses >= threshold:
    await self._auto_pause_trading("consecutive_losses", ...)
```

---

## Important Issues

### IMPORTANT-1: Smart exit labels exits as `"take_profit"` when net P&L is negative after fees

**Confidence: 85**

**File:** `src/execution/executor.py:1177-1211` (stagnation tightening), `executor.py:1253-1265` (TP check)

Exact mechanism:
1. ATR-based stagnation detection at line 1177 tightens TP to 40% of original distance (severe stagnation: `stagnation_ratio < 0.2`, `age_minutes > 45`)
2. Example: entry=$1.000, original TP=$1.010, tightened TP=$1.004
3. Price reaches $1.004 → regular TP check at line 1256 fires → closes with `reason="take_profit"`
4. `_close_position` computes gross P&L = +0.4% but total fees = 0.52% round-trip → net P&L = -0.12%
5. Dashboard shows `reason="take_profit"` with negative P&L

The logic is correct (exiting a stagnating position is right), but the label is misleading.

**Fix option A:** Rename the exit reason when fees make it a net loss:

```python
# In _manage_position_inner, in the TP check block (around line 1258):
tp_reason = "take_profit"
# Estimate fees to detect fee-loss scenario
rt_fees = entry_price * self.taker_fee * 2  # rough round-trip
gross_pnl = abs(current_price - entry_price)
if gross_pnl < rt_fees:
    tp_reason = "stagnation_exit"
await self._close_position(
    trade_id, pair, side, entry_price, current_price, quantity, tp_reason, ...
)
```

**Fix option B:** In the stagnation tightening block, ensure the tightened TP is always fee-profitable:

```python
# After computing new_tp for side=="buy":
min_tp_for_fees = entry_price * (1 + self.taker_fee * 2 + 0.001)
new_tp = max(new_tp, min_tp_for_fees)
# After computing new_tp for side=="sell":
max_tp_for_fees = entry_price * (1 - self.taker_fee * 2 - 0.001)
new_tp = min(new_tp, max_tp_for_fees)
```

Fix option B is cleaner as it prevents the loss scenario entirely.

---

### IMPORTANT-2: `_daily_reset_date = ""` causes `_consecutive_losses` to silently reset on every restart

**Confidence: 82**

**File:** `src/execution/risk_manager.py:149`

```python
self._daily_reset_date: str = ""  # BUG: first call always triggers reset
```

```python
# risk_manager.py:953-961
def _check_daily_reset(self) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != self._daily_reset_date:   # "" != "2026-02-28" → True on first call
        self._consecutive_losses = 0      # ← reset fires on every restart
        ...
        self._daily_reset_date = today
```

`_check_daily_reset` is called from `_position_management_loop` (`engine.py:1943`) at `position_check_interval` frequency (every second). On every restart, the first call immediately fires the daily reset, clearing `_consecutive_losses` regardless of prior session losses. Combined with in-memory-only storage, any restart wipes the loss streak counter. In a crash-restart scenario (engine restarts repeatedly while generating losses), the consecutive-loss circuit breaker never accumulates enough count to fire.

**Fix:** Initialize to today's date:

```python
self._daily_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
```

---

### IMPORTANT-3: `ControlRouter.resume()` sets non-existent attributes on `StockSwingEngine`

**Confidence: 80**

**File:** `src/core/control_router.py:93-96`

```python
self._engine._auto_pause_reason = ""
self._engine._stale_check_count = 0          # does not exist on StockSwingEngine
self._engine._ws_disconnected_since = None   # does not exist on StockSwingEngine
```

`StockSwingEngine` does not define `_stale_check_count` or `_ws_disconnected_since`. Python silently creates these as new instance attributes. The `ControlRouter.resume()` protocol contract (declared via `EngineInterface` at `control_router.py:19–46`) lists these as required attributes, yet `StockSwingEngine` does not satisfy the contract. This doesn't cause a runtime error today but creates debugging confusion.

**Fix:**

```python
if hasattr(self._engine, "_stale_check_count"):
    self._engine._stale_check_count = 0
if hasattr(self._engine, "_ws_disconnected_since"):
    self._engine._ws_disconnected_since = None
```

Or add the attributes to `StockSwingEngine.__init__()`:

```python
# In StockSwingEngine.__init__():
self._stale_check_count: int = 0
self._ws_disconnected_since: Optional[float] = None
```

---

### IMPORTANT-4: `get_pnl()` and `get_risk()` in ControlRouter crash if `risk_manager` is None

**Confidence: 80**

**File:** `src/core/control_router.py:174,192`

```python
# Line 174 — no guard for risk_manager being None
risk = self._engine.risk_manager.get_risk_report()

# Line 192 — same issue
return self._engine.risk_manager.get_risk_report()
```

During the window between `_init_db` completion and `_init_risk_and_execution` completion (engine startup sequence in `main.py`), `risk_manager` is `None`. Any dashboard poll during this window hitting `/api/v1/pnl` or `/api/v1/risk` would raise `AttributeError`.

**Fix:**

```python
# get_pnl():
risk = self._engine.risk_manager.get_risk_report() if getattr(self._engine, "risk_manager", None) else {}

# get_risk():
if not self._engine or not getattr(self._engine, "risk_manager", None):
    return {}
return self._engine.risk_manager.get_risk_report()
```

---

## Root Cause Analysis: Why All Trades Are Losing

The user reports all recent trades losing $2–$3 on XRP, AVAX, ETH, LINK. Based on code analysis:

**Primary cause: Fee erosion at low R:R with high stop-out rate**

With `min_risk_reward_ratio: 1.0` and `taker_fee: 0.0026`:
- Round-trip fee = 0.52%
- At 1:1 R:R, a profitable trade needs to move at least 0.52% just to break even
- If win rate is 40% (typical for cold-start ML + solo signals), EV = 0.4 × (gain - 0.52%) + 0.6 × (-loss - 0.52%) → negative EV when gain = loss (1:1 R:R)
- For 1:1 R:R to be EV-positive: win_rate > 0.52/(1.52) = 34%. The system is near breakeven theoretically

**Secondary cause: Solo signals with cold-start ML are low quality**

With `allow_any_solo: true` and `solo_min_confidence: 0.68`, single-strategy signals with blended confidence of 0.68 are executed. The cold-start predictor returns ~0.50 base confidence (random-walk for untrained TFLite), and solo signals blend at 70% strategy + 30% AI (`engine.py:1756`): `0.7 × 0.75 + 0.3 × 0.50 = 0.675`. These barely exceed the 0.68 threshold and do not represent strong directional conviction.

**Tertiary cause: OBI always 0 (known Kraken WS book data issue)**

Order Book Imbalance is always 0 due to missing WS book data. Trades enter without confirming order flow alignment, which historically filters out ~20% of false signals.

**Recommendation:** For the 48h challenge remaining time, raise `min_risk_reward_ratio` from 1.0 to 1.5 (minimum 1.5:1 R:R). This reduces trade frequency but each winning trade covers 3 losing trades rather than 1. Also set `allow_any_solo: false` temporarily to require at least 2 strategies to agree.

---

## Configuration Audit

### Config vs Code Default Divergence

| Setting | config.yaml | Code Default | Active |
|---------|-------------|--------------|--------|
| `consecutive_losses_pause_threshold` | 5 | 4 | 5 (config wins) |
| `drawdown_pause_pct` | 8.0 | 8.0 | 8.0 |
| `ws_disconnect_pause_after_seconds` | 300 | 300 | 300 |
| `stale_data_pause_after_checks` | 3 | 3 | 3 |

The `consecutive_losses_pause_threshold` divergence (config=5, code=4) is intentional for 48h challenge tuning but creates a silent footgun if the config key is deleted.

### CSV Column `"reason"` is Always Empty

**File:** `src/api/server.py:1689-1699`

The CSV export includes `"reason"` as a column but there is no `reason` column in the `trades` table. `r.get("reason", "")` always returns `""`. Close reasons are stored in `metadata` JSON. The CSV produced by the current code always has a blank "reason" column.

**Fix:** Extract reason from metadata:

```python
# In _iter_csv() at line 1699:
for r in rows:
    meta = json.loads(r.get("metadata") or "{}")
    r_with_reason = dict(r)
    r_with_reason["reason"] = meta.get("close_reason", "")
    w.writerow([r_with_reason.get(c, "") for c in cols])
```

---

## Summary: Issues by Priority

| Priority | Issue | Files | Fix Complexity |
|----------|-------|-------|----------------|
| **P0** | Ghost reconciliation crashes — `close_reason` not in whitelist | `executor.py:344` | 1 line |
| **P0** | CSV export HTTP 400 in multi-engine — broken download | `server.py:1662` | 15 lines |
| **P1** | Resume re-triggers immediately — no auto-pause grace period | `engine.py:251`, `control_router.py:94` | 10 lines |
| **P1** | Smart exit "take_profit" label on fee-negative trades | `executor.py:1177-1211` | 8 lines |
| **P2** | `_daily_reset_date = ""` — consecutive_losses cleared on every restart | `risk_manager.py:149` | 1 line |
| **P2** | `ControlRouter.resume()` sets phantom attrs on StockSwingEngine | `control_router.py:93-96` | 4 lines |
| **P2** | `get_pnl()` / `get_risk()` crash if risk_manager is None | `control_router.py:174,192` | 4 lines |
| **P3** | CSV "reason" column always blank | `server.py:1699` | 5 lines |
| **P3** | `import math as _math` inside hot loop | `executor.py:1167` | 1 line |
| **INFO** | All trades losing: fee erosion at 1:1 R:R + solo signals + no OBI | Config + known WS issue | Config change |

---

*Review completed: 2026-02-28. 15 source files examined. 4 user-reported issues root-caused.*
