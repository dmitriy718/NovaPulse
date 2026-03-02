# NovaPulse v5.0.0 — Second-Pass Code Review
**Date:** 2026-02-28
**Scope:** Second review pass after Feb28 bug fixes. Focus on NEW bugs not caught in the first pass.

**7 issues found. 2 P1, 5 P2.**

---

## P1-1: `self._regime_predictor` Never Stored — GC Risk + Dashboard Always Shows Disabled

**Confidence: 100%**
**File:** `src/core/engine.py:701-710`

`RegimeTransitionPredictor` instantiated as local variable, never assigned to `self._regime_predictor`. Dashboard's `_collect_feature_status()` always reports `{"enabled": False}`. Object may be garbage-collected after `_init_ai_components()` returns.

**Fix:** Change to `self._regime_predictor = RegimeTransitionPredictor(...)` and add `self._regime_predictor = None` to `__init__`.

---

## P1-2: Race Condition — Concurrent Signals Can Both Pass Duplicate-Pair Gate

**Confidence: 87%**
**File:** `src/execution/executor.py:576-587`

The `await self.db.get_open_trades()` in `_check_gates()` is a yield point. Two signals for the same pair can both read zero open trades and both pass the gate. No per-pair lock guards the check-then-insert sequence.

**Fix:** Add per-pair asyncio.Lock in `execute_signal()`.

---

## P2-1: Wrong Metadata Key in Stagnation TP Fee Check

**Confidence: 100%**
**File:** `src/execution/executor.py:1210`

Uses `meta.get("taker_fee", 0.001)` but actual key is `"exit_fee_rate"`. Always falls back to 0.1% instead of Kraken's 0.26%.

**Fix:** `taker_fee = float(meta.get("exit_fee_rate", self.taker_fee) or self.taker_fee)`

---

## P2-2: CSV `size_usd` Always Empty

**Confidence: 100%**
**File:** `src/api/server.py:1706`

`size_usd` stored in metadata JSON, not a DB column. `r.get("size_usd", "")` always returns `""`.

**Fix:** Parse metadata JSON to extract `size_usd`.

---

## P2-3: `exec_confidence` Silently Clamped to Max 0.75

**Confidence: 95%**
**File:** `src/core/engine.py:1668`

Config values above 0.75 silently ignored. No log warning.

**Fix:** Add warning log when config exceeds cap.

---

## P2-4: `min_confluence` Silently Clamped to Min 2

**Confidence: 95%**
**File:** `src/core/engine.py:1666`

Config `confluence_threshold: 1` silently overridden to 2.

**Fix:** Enforce in config validation or remove runtime clamp.

---

## P2-5: `get_positions()` — `market_data` Accessed Without None-Guard

**Confidence: 90%**
**File:** `src/core/control_router.py:192-194`

`self._engine.market_data.get_latest_price()` called without checking if `market_data` is None. Can crash during early init.

**Fix:** Add `md = getattr(self._engine, "market_data", None)` guard.

---

## Summary

| ID | Priority | File | Issue |
|----|----------|------|-------|
| P1-1 | P1 | engine.py:701 | regime_predictor never stored on self |
| P1-2 | P1 | executor.py:576 | duplicate-pair gate race condition |
| P2-1 | P2 | executor.py:1210 | wrong metadata key "taker_fee" → "exit_fee_rate" |
| P2-2 | P2 | server.py:1706 | CSV size_usd always empty |
| P2-3 | P2 | engine.py:1668 | exec_confidence silently capped at 0.75 |
| P2-4 | P2 | engine.py:1666 | min_confluence silently floored at 2 |
| P2-5 | P2 | control_router.py:193 | market_data None guard missing |
