# NovaPulse + Horizon Alerts — Brutally Honest Project Assessment
**Date:** 2026-02-28 | **Reviewer:** Claude Code (automated)

---

## What You've Built

Two interconnected systems: **NovaPulse** (autonomous trading bot, ~15k LOC Python) and **Horizon Alerts** (customer-facing SaaS platform, ~8k LOC TypeScript). Together they form a multi-exchange algorithmic trading platform with a web dashboard, email alerts, gamification, and social features.

---

## Architecture

### Strengths
- **Multi-engine design is genuinely well-architected.** The `MultiEngineHub` / `ControlRouter` abstraction lets you run Kraken, Coinbase, and Stocks engines independently with unified API. Adding a new exchange is a config change + adapter, not a rewrite.
- **Confluence voting system is clever.** 12 strategies vote independently, weighted by regime and recent performance. This is meaningfully better than single-strategy bots and provides natural diversification.
- **SQLite + WAL mode is the right call** for a single-node deployment. No unnecessary Postgres/Redis complexity. The DB schema is clean and well-indexed.
- **Risk management is layered and thorough.** Per-trade stops, per-strategy cooldowns, daily loss limits, consecutive-loss circuit breakers, cross-engine exposure caps, correlation-based sizing. Most retail trading bots have maybe one of these.
- **The v5.0 feature set is ambitious and mostly well-integrated.** Event calendar blackouts, lead-lag intelligence, anomaly detection, ensemble ML, Bayesian optimization — all wired into the existing pipeline without breaking the core loop.

### Weaknesses
- **Single point of failure.** One Docker container, one server, one SQLite file. If the process crashes at 3 AM, there is no failover. The health check exists but nobody gets paged.
- **No replay/backtest framework.** You cannot run historical data through the strategy pipeline to validate changes before deploying. Every config change is a live experiment.
- **The codebase has accumulated complexity debt.** `engine.py` is 1,800+ lines. `executor.py` is 1,400+. `server.py` is 1,700+. These files do too many things and changes in one area risk breaking another.
- **v5.0 advanced features are all `enabled: false`.** Ten features were built, tested, merged — and none are running in production. The value delivered is currently zero until they're turned on and validated.

---

## Trading Engine Analysis

### What Works
- The scan-evaluate-execute loop is solid. 15-second intervals with multi-timeframe confirmation (5m + 15m) and regime-aware sizing.
- Smart exit system with trailing stops, stagnation detection, and adaptive activation is legitimately sophisticated.
- Funding rate integration and session-aware trading (crypto pauses during stock hours, vice versa) show operational maturity.

### What Doesn't
- **No live P&L tracking against benchmark.** You don't know if NovaPulse outperforms buy-and-hold BTC. Without this, you can't prove the bot adds value.
- **Order book data is broken.** Kraken WS book subscriptions never fire. OBI (Order Book Imbalance) is always 0. The spread gate was patched to let trades through with missing data, but this means every trade decision is made without depth information. This is the single biggest data quality gap.
- **Stagnation exit fee calculation was wrong** (using hardcoded 0.1% instead of actual 0.26%). Fixed in this session, but it means every stagnation exit since the feature launched may have been slightly below breakeven.
- **Cold-start period is fragile.** The first few minutes after restart have relaxed gates and no trained ML model. Trades taken in this window have lower expected quality.

---

## Security Posture

### NovaPulse
- **Good:** API key auth on dashboard, bcrypt password hashing (with the $ escaping fix), secrets isolated in mounted volume.
- **Bad:** Dashboard serves over HTTP (no TLS at the app layer — relies on Docker network/reverse proxy). No CSRF protection. API keys are static strings, not rotated.

### Horizon Alerts
- **Good:** JWT auth, rate limiting on login (just added), SSRF protection via `redirect: "error"`, HMAC-signed unsubscribe links, input validation on most routes.
- **Bad:** Unsubscribe HMAC shares the JWT signing key (fixed in review, but needs a separate env var in production). No CSP headers. Newsletter endpoint was unprotected until this session. The `lock-status` endpoint was an unauthenticated DB query oracle until this session.
- **Overall:** Adequate for a low-value-target SaaS. Would not pass a professional pentest without the fixes applied today.

---

## UX/DX Quality

### Dashboard (NovaPulse)
- Clean, functional single-page app. Dark theme, real-time WebSocket updates, chart sharing with 8 platforms.
- Missing: No mobile responsiveness. No historical P&L charts. No strategy-level drill-down. The "Advanced Features" panel shows 10 features all disabled — this is confusing to users who don't know what they are.

### Dashboard (Horizon)
- Polished Next.js app with gamification (ranks, XP, achievements), real-time polling, settings page.
- Good: The error state handling (just fixed) properly distinguishes "no bot configured" from "API error." The share button is well-integrated.
- Missing: No WebSocket connection (polling only — stale data between intervals). Chart modal had no keyboard accessibility until this session. Trade CSV download was completely broken until this session.

### Developer Experience
- Config is YAML-based and comprehensive but has silent clamps (confidence capped at 0.75, confluence floored at 2) that override config values without warning. Fixed with warnings in this session.
- Test suite is solid (319 tests for NovaPulse, TypeScript strict mode for Horizon). No CI/CD pipeline — tests run manually.
- Deployment is rsync + docker restart. Works fine at this scale but doesn't scale to a team.

---

## Where It's Lacking — Improvement Plan

### Tier 1: Do This Week
1. **Enable and validate v5.0 features one at a time.** Start with Event Calendar (lowest risk) and Anomaly Detector (immediate safety value). Each feature should run 48h before enabling the next.
2. **Fix the Kraken order book subscription.** This is the #1 data quality gap. Debug at WS v2 protocol level — the subscription sends but callbacks never fire. Without book data, OBI-based confluence votes and liquidity sizing are dead features.
3. **Add benchmark tracking.** Log BTC buy-and-hold returns alongside bot returns. Display on dashboard. If the bot can't beat holding BTC, the strategies need tuning.

### Tier 2: Do This Month
4. **Build a backtest framework.** Record all market data to a replay log. Build a runner that feeds historical data through the strategy pipeline. Without this, every config change is a coin flip.
5. **Set up CI/CD.** GitHub Actions running tests on push, auto-deploy on merge to main. The test suite exists — make it mandatory.
6. **Add monitoring and alerting.** Prometheus metrics, Grafana dashboard, PagerDuty integration. If the bot crashes or hits max drawdown at 3 AM, you should know within 5 minutes.
7. **Split the God files.** `engine.py`, `executor.py`, and `server.py` each need to be broken into focused modules. The engine loop, strategy evaluation, and signal processing should be separate concerns.

### Tier 3: Do This Quarter
8. **Add TLS and CSRF to the NovaPulse dashboard.** Even behind Docker, defense in depth matters.
9. **Implement proper secret rotation.** API keys should have expiry dates and automated rotation.
10. **Build a multi-node deployment.** Active-passive failover with shared state in Postgres. The current single-container setup is a single point of failure for a system managing real money.

---

## Bottom Line

NovaPulse is a **genuinely impressive solo-developer trading system** — the multi-engine architecture, confluence voting, layered risk management, and v5.0 feature breadth put it well above typical retail trading bots. Horizon Alerts is a **functional but early-stage SaaS wrapper** that needs more polish before charging customers.

The critical gap is **validation**: you've built sophisticated trading logic but have no backtest framework, no benchmark comparison, and no way to prove the system generates alpha. The order book data being completely broken means two of your confluence signals (OBI, liquidity) are non-functional. Half of v5.0's advanced features have never run in production.

The code quality is solid but the operational maturity is not there yet. No CI/CD, no monitoring, no failover, manual deployments. This is fine for a solo project but would be the first thing to fix before onboarding users or scaling up.

**If this were a startup pitch:** the technology is promising but unproven. Ship the backtest framework, prove alpha over 90 days of live data, fix the order book pipeline, and you have something worth showing to investors. Right now it's an impressive engineering project that hasn't yet proven it makes money.
