# NovaPulse v5.0.0 — Rollout Prep & Code Review

## Issues Found & Fixed

*Review started: 2026-02-27*
*Reviewer: Claude Code comprehensive audit*

---

### CRITICAL — Root Causes for Zero Trading

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1 | **Scan cycle logs at DEBUG severity** — log level is INFO, so all scan activity was invisible. 2282 scans ran but zero output. | `engine.py` | Changed severity from `"debug"` to `"info"` |
| 2 | **10+ silent rejection gates** — bare `continue`/`return False` with no logging. Impossible to diagnose why signals were rejected. | `engine.py`, `executor.py`, `confluence.py` | Added `log_thought("filter", ...)` to every gate |
| 3 | **Performance endpoint data overwrite** — `{**stats, **risk_report}` caused risk_manager's in-memory `open_positions: 0` to overwrite DB's correct count of 4. | `server.py:1787` | Reversed merge: `{**risk_report, **stats}` so DB values win |
| 4 | **Strategy guardrail AND→OR bug** — required BOTH win_rate < 0.35 AND profit_factor < 1.0 to disable. A strategy with 0% win rate but PF=1.1 would never be disabled. | `confluence.py:550` | Changed `and` to `or` |
| 5 | **Version string still "4.5.0"** — `src/__init__.py` and `config.yaml` both showed wrong version. | `__init__.py`, `config.yaml` | Updated to "5.0.0" |

### HIGH — Signal Pipeline Bottlenecks

| # | Issue | File | Fix |
|---|-------|------|-----|
| 6 | **Funding rate 503 storm** — no retry/backoff; Kraken Futures 503s caused 20+ rapid-fire errors in 2 minutes. | `funding_rates.py` | Added exponential backoff (3 retries) + circuit breaker (3 failures → 5 min cooldown) |
| 7 | **Quiet hours silent rejection** — UTC hours 2,3,4 silently dropped signals without logging. | `executor.py:537-540` | Added `log_thought("filter", ...)` with hour info |
| 8 | **Duplicate pair silent rejection** — already-open pair blocked with bare `return False`. | `executor.py:569` | Added `log_thought("filter", ...)` |
| 9 | **Correlation group silent rejection** — group limit hit with bare `return False`. | `executor.py:579` | Added `log_thought("filter", ...)` with group name and count |
| 10 | **Signal validation silent rejections** — _validate_signal rejected for decay/age/floor with no logging. | `executor.py:491-514` | Added `logger.debug()` for age cutoff, decay floor, timestamp parse failure |
| 11 | **max_drawdown_pct wrong aggregation** — used `max(per_engine)` instead of aggregate (sum peak - sum bankroll). | `server.py` | Computed from summed peak_bankroll and bankroll |

### MEDIUM — Confluence Silent Returns

| # | Issue | File | Fix |
|---|-------|------|-----|
| 12 | **Stale data NEUTRAL** — returned NEUTRAL with zero logging when pair not warmed up or stale. | `confluence.py:350` | Added `logger.debug()` |
| 13 | **Empty signals NEUTRAL** — returned NEUTRAL when no strategies produced signals. | `confluence.py:801` | Added `logger.debug()` |
| 14 | **No consensus NEUTRAL** — tied long/short count returned NEUTRAL silently. | `confluence.py:922` | Added `logger.debug()` with long/short counts |
| 15 | **Multi-timeframe rejection** — agreement < min_agreement returned NEUTRAL silently. | `confluence.py:686` | Added `logger.debug()` with agreement counts and TF directions |

### INFORMATIONAL — Noted but Not Changed (Trading Parameters)

| # | Item | Current Value | Notes |
|---|------|---------------|-------|
| 16 | Confluence threshold | 3 | Requires 3/12 strategies to agree. Conservative. |
| 17 | High-vol confluence | 3 | Can go to 4-5 with choppy penalty. Very restrictive. |
| 18 | Multi-TF min agreement | 2 of 2 | Both 5m and 15m must agree — 100% unanimity. Comment says "2 of 3" but only 2 TFs configured. |
| 19 | Signal decay | 2%/sec after 5s | A 0.55 confidence signal dies in ~7.5 seconds. |
| 20 | Confidence floor | 0.50 (hardcoded) | Config says 0.55 but executor floor is 0.50. Safety net works but creates confusion. |
| 21 | Global cooldown after loss | 1800s (30 min) | Aggressive — prevents recovery trades. |
| 22 | Drawdown sizing at 18%+ | 0.15× normal | Severely restricts position sizes during drawdowns. |
| 23 | Regime gating | Removes 3/12 strategies | Range: trend/ichimoku/supertrend gated. Trend: mean_rev/stoch_div/reversal gated. Threshold not adjusted. |

---

## Full Gate Inventory (26 gates a signal must pass)

### Confluence Layer (analyze_pair → _compute_confluence)
1. Data warmup check (50 bars minimum)
2. Data staleness check (180s max)
3. Per-strategy timeout (5s)
4. Strategy cooldown filter
5. Regime binary gating (3 strategies removed)
6. Strategy guardrail (win rate OR profit factor)
7. Choppiness index penalty
8. Direction consensus (majority required)
9. Multi-timeframe agreement (2/2 required)

### Engine Scan Loop
10. Confluence threshold (≥3 votes)
11. Risk/reward ratio (≥1.0)
12. Spread absolute check
13. Spread-to-ATR ratio check

### Executor (_validate_signal)
14. NEUTRAL direction rejection
15. Signal age hard cutoff (60s)
16. Confidence decay floor (0.50)

### Executor (_check_gates)
17. Event calendar blackout
18. Quiet hours (UTC 2,3,4)
19. Trade-rate throttle (max/hour)
20. Duplicate pair check
21. Correlation group limit

### Risk Manager
22. Circuit breaker (bankroll depleted)
23. Global cooldown (30 min after loss)
24. Daily loss limit (5%)
25. Per-pair cooldown (5 min)
26. Max concurrent positions (5)

### Position Sizing (can reduce to $0)
27. Drawdown factor (10% at extreme)
28. Loss streak factor (40-70% reduction)
29. Spread penalty (50-100%)
30. Volatility factor (60% in high vol)
31. Correlation factor (50-100% reduction)
32. Portfolio heat limit (50% of bankroll)
33. Liquidity depth cap

---

## Files Modified in This Review

- `src/__init__.py` — version 5.0.0
- `src/exchange/funding_rates.py` — retry + circuit breaker
- `src/core/engine.py` — scan loop logging + severity + spread gate fix (allow missing book data) + cold-start gating relaxed
- `src/api/server.py` — merge order fix + drawdown aggregation
- `src/execution/executor.py` — quiet hours + duplicate + correlation + validation logging
- `src/ai/confluence.py` — silent NEUTRAL logging + guardrail AND→OR
- `config/config.yaml` — version 5.0.0 + 48h challenge tuning

---

## 48-Hour Challenge Config (2026-02-27)

*Goal: 6-10 trades/day while maintaining positive P&L*

### Config Changes (from pre-challenge baseline)

| Setting | Before | After | Rationale |
|---------|--------|-------|-----------|
| confluence_threshold | 3 | 2 | 2 strategies = tradeable |
| high_vol_confluence_threshold | 3 | 2 | Match base |
| multi_timeframe_min_agreement | 2 | 1 | Primary TF drives, 5m won't veto |
| min_confidence | 0.55 | 0.50 | Align with executor floor |
| allow_any_solo | false | true | Solo trades with strict confidence gate |
| solo_min_confidence | 0.67 | 0.68 | Strict gate for solo non-Keltner |
| keltner_solo_min_confidence | 0.60 | 0.58 | Keltner proven, relax slightly |
| session.max_penalty | 0.70 | 0.85 | Less aggressive session killing |
| scan_interval_seconds | 20 | 15 | Faster scan cadence |
| max_concurrent_positions | 8 | 10 | More simultaneous positions |
| cooldown_seconds | 30 | 20 | Faster per-pair re-entry |
| strategy_cooldowns | 90 | 60 | Faster strategy re-fire |
| quiet_hours_utc | [2,3,4] | [3] | Only deepest dead hour |
| global_cooldown_on_loss | 60 | 30 | Faster recovery |
| consecutive_losses_pause | 4 | 5 | Slightly more tolerant |

### Code Changes for Challenge

| File | Change | Rationale |
|------|--------|-----------|
| engine.py | Cold-start gating: min_confluence 3→2, min_confidence 0.60→0.55 | Don't override config tuning |
| engine.py | Spread gate: allow trade through when spread=0 (no book data) | Book subscription not delivering — don't block on missing data |
| engine.py | Filter log severity: debug→info | Visible in dashboard thought feed |

### Early Results (first 15 min)

5 crypto trades opened with confidence 0.706-0.934. Strategies: funding_rate, market_structure, keltner. Pairs: BTC, ETH, SOL, ADA, XRP. All within risk parameters.
