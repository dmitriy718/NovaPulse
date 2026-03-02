# Nova|Pulse by Horizon Services -- Internal Documentation

**Product:** Nova|Pulse AI Trading Platform by Horizon Services
**Version:** 5.0.0
**Audience:** Horizon Services support team, developers, and DevOps engineers
**Last Updated:** 2026-03-02

This documentation covers both the **NovaPulse trading bot** (Python) and the **Horizon web platform** (Next.js/Fastify).

---

## Table of Contents

### NovaPulse Trading Bot

| # | Document | Description |
|---|----------|-------------|
| 1 | [Architecture](Architecture.md) | System overview, component map, data flow, deployment model, background tasks |
| 2 | [Trading Engine](Trading-Engine.md) | BotEngine orchestrator, 12 strategies, confluence, adaptive weighting, regime detection, MTF |
| 3 | [Confluence Engine](Confluence-Engine.md) | Deep dive into confluence detector, family diversity scoring, opposition penalty, OBI votes |
| 4 | [Risk Management](Risk-Management.md) | Kelly Criterion sizing, ATR stops, trailing/breakeven, circuit breakers, smart exit, structural stops, liquidity sizing |
| 5 | [Adaptive Exits](Adaptive-Exits.md) | Time-based exit tightening, vol-regime trailing stops, smart exit tiers |
| 6 | [Exchange Integration](Exchange-Integration.md) | Kraken WS v2, Coinbase Advanced Trade, exception hierarchy, order flow, reconnection |
| 7 | [WebSocket Integration](WebSocket-Integration.md) | Kraken WS v2 and Coinbase WS implementation details, subscription management |
| 8 | [Multi-Engine Architecture](Multi-Engine-Architecture.md) | MultiEngineHub, MultiControlRouter, priority scheduler, cross-engine coordination |
| 9 | [Stock Swing Engine](Stock-Swing-Engine.md) | Stock trading: Polygon data, Alpaca execution, universe scanner, swing strategy |
| 10 | [Config Reference](Config-Reference.md) | Complete config.yaml field reference with environment variable overrides |
| 11 | [Database Schema](Database-Schema.md) | SQLite tables, WAL mode, migrations, query patterns |
| 12 | [Data Formats](Data-Formats.md) | REST/WS message formats, structlog JSON, Elasticsearch indexes |
| 13 | [ML Training Pipeline](ML-Training-Pipeline.md) | TFLite training, continuous learner, auto-tuner, cross-exchange aggregation |
| 14 | [Indicator Library](Indicator-Library.md) | Technical indicators, IndicatorCache, vectorized computation |
| 15 | [Global Risk Aggregation](Global-Risk-Aggregation.md) | Cross-engine exposure tracking via GlobalRiskAggregator singleton |
| 16 | [Correlation Sizing](Correlation-Sizing.md) | Pearson correlation-based position size reduction |
| 17 | [Funding Rate Integration](Funding-Rate-Integration.md) | Kraken Futures funding rate client and strategy |
| 18 | [Market Structure Strategy](Market-Structure-Strategy.md) | Swing-based trend structure detection and pullback entries |
| 19 | [VWAP Strategy](VWAP-Strategy.md) | VWAP momentum alpha strategy implementation |
| 20 | [Advanced Features](Advanced-Features.md) | v5.0 features: event calendar, lead-lag, regime predictor, on-chain, structural stops, liquidity sizing, anomaly detector, attribution, ensemble ML, Bayesian optimizer |
| 21 | [Elasticsearch Pipeline](Elasticsearch-Pipeline.md) | ES client, ingestion, enrichment, index management, external data collection |
| 22 | [Security](Security.md) | Authentication, rate limiting, brute-force protection, CORS, CSP, CSRF, secrets management |
| 23 | [Operations](Operations.md) | Day-to-day Docker deployment, log inspection, DB queries, mode transitions, rsync deploy |
| 24 | [Runbooks](Runbooks.md) | Step-by-step incident response procedures |
| 25 | [Support Triage](Support-Triage.md) | Customer issue triage by priority level |
| 26 | [Credential Rotation](Credential-Rotation.md) | Zero-downtime key rotation for all external services |
| 27 | [Dashboard Integration](Dashboard-Integration.md) | horizonsvc.com dashboard: Caddy proxy, bot_connections, Fastify proxy routes, SSRF protection |
| 28 | [FAQ](FAQ.md) | Internal frequently asked questions |

### Horizon Web Platform

| # | Document | Description |
|---|----------|-------------|
| 29 | [Horizon Architecture](Horizon-Architecture.md) | System overview, tech stack (Next.js 15, Fastify, PostgreSQL), service topology, data flow |
| 30 | [Horizon API Reference](Horizon-API-Reference.md) | All API endpoints: auth, profile, billing, bot proxy, scanner, tickets, newsletter |
| 31 | [Horizon Authentication](Horizon-Authentication.md) | Firebase setup, token verification flow, account lockout, login tracking, auth context |
| 32 | [Horizon Billing (Stripe)](Horizon-Billing-Stripe.md) | Stripe checkout flow, webhook handling, entitlement management, customer portal |
| 33 | [Horizon Bot Integration](Horizon-Bot-Integration.md) | Bot proxy architecture, SSRF protection, connection lifecycle, bot monitor service |
| 34 | [Horizon Database Schema](Horizon-Database-Schema.md) | PostgreSQL tables (users, stripe_entitlements, bot_connections, tickets, signals), migrations |
| 35 | [Horizon Deployment](Horizon-Deployment.md) | Docker Compose, Nginx reverse proxy, Ansible automation, environment variables |
| 36 | [Horizon Email System](Horizon-Email-System.md) | SMTP configuration, template library, preference checking, unsubscribe mechanism, bot monitor |
| 37 | [Horizon SEO Guide](Horizon-SEO-Guide.md) | Metadata, JSON-LD structured data, sitemap, robots.txt, Open Graph/Twitter cards |
| 38 | [Horizon Security](Horizon-Security.md) | CSP headers, rate limiting, CORS, HMAC tokens, input validation (Zod), SSRF prevention |

---

## Quick Reference -- NovaPulse Bot

| Item | Value |
|------|-------|
| Main entry point | `main.py` |
| Dashboard port (container) | 8080 |
| Dashboard port (host default) | 8090 |
| Default database | `data/trading.db` (SQLite, WAL mode) |
| Config file | `config/config.yaml` |
| Secrets file | `.secrets/env` (volume-mounted, read by `src/utils/secrets.py`) |
| Docker service | `trading-bot` (container name: `novatrader-trading-bot-1`) |
| Python versions | 3.11, 3.12, 3.13 |
| Primary exchange | Kraken (WS v2 + REST) |
| Secondary exchange | Coinbase (Advanced Trade REST + WS) |
| Stock execution | Alpaca (REST) |
| Stock data | Polygon.io (REST, free tier = grouped daily bars) |
| Strategies | 12 (Keltner 0.25, MeanRev 0.20, VolSqueeze 0.18, VWAP 0.15, OrderFlow 0.12, MarketStructure 0.12, Supertrend 0.12, FundingRate 0.10, Trend 0.08, Ichimoku 0.08, StochDiv 0.06, Reversal 0.06) |
| Trading modes | `paper` (default), `live` |
| Test suite | 319 passed, 20 skipped (optional deps: lightgbm 9, optuna 11) |
| Ops server | 165.245.143.68, user `ops`, SSH key `~/.ssh/horizon`, path `/home/ops/novatrader/` |
| Deploy method | rsync (NOT git on server) |

## Quick Reference -- Horizon Platform

| Item | Value |
|------|-------|
| Frontend | Next.js 15 (App Router), React 19, Tailwind CSS |
| API | Fastify 4, TypeScript |
| Database | PostgreSQL 15 |
| Cache | Redis 7 |
| Auth | Firebase Auth (client + Admin SDK) |
| Payments | Stripe (Checkout, Webhooks, Customer Portal) |
| Email | Nodemailer (SMTP) with HTML templates |
| Analytics | PostHog |
| Deployment | Docker Compose, Nginx, Ansible |
| Testing | Vitest (unit), Playwright (E2E) |
| Validation | Zod |
| API port | 4000 (behind Nginx at `/api/`) |
| Web port | 3000 (behind Nginx at `/`) |
| Production URL | horizonsvc.com |

---

## Architecture at a Glance

### NovaPulse Bot

```
Market Data (Kraken WS v2 / Coinbase WS / REST poll)
         |
    MarketDataCache (RingBuffer arrays per pair)
         |
    BotEngine (main.py -> engine.py)
         |
    ConfluenceDetector (12 strategies x N timeframes)
         |
    AI Intelligence Layer
    (TFLite predictor, SessionAnalyzer, LeadLag, RegimePredictor, OnChain, EnsembleML)
         |
    RiskManager (Kelly sizing, ATR stops, correlation, structural stops, liquidity)
         |
    TradeExecutor (limit entry + chase, market exit, smart exit tiers)
         |
    Exchange REST API (Kraken / Coinbase / Alpaca)
         |
    DatabaseManager (SQLite WAL)
         |
    DashboardServer (FastAPI + uvicorn, WS live feed)
```

### Horizon Platform

```
[Browser] --> [Nginx (SSL)] --> [Next.js Web App :3000]
                            --> [Fastify API :4000] --> [PostgreSQL :5432]
                                                   --> [Redis :6379]
                                                   --> [NovaPulse Bot :8080] (per user)

[Signal Engine] --> [PostgreSQL]
[Automation]    --> [PostgreSQL]
```

---

## Key Pitfalls (Quick Reference)

| Pitfall | Details |
|---------|---------|
| DatabaseManager has no `.execute()` | Use `db._db.execute()` + `db._db.commit()` |
| Docker Compose eats `$` in .env | Secrets go in `.secrets/env` (volume-mount), not `.env` |
| Bcrypt `$$` escaping unreliable | `.secrets/env` bypasses Docker Compose interpolation entirely |
| `_detect_regime()` returns 4 values | DO NOT store on self (race condition between scan loop iterations) |
| Polygon snapshots need paid tier | Free tier returns 403; use `get_grouped_daily_bars()` fallback |
| Monday previous trading day | offset=3 (Friday), not offset=1 (Sunday) |
| Scanner labels in multi-engine | `"AAPL (stocks:default)"` not plain `"AAPL"` |
| Kraken WS 1013 | Reconnect-requested close code, handled with retry backoff |
| `op inject` needs `{{ op://... }}` | Use `op read` per-ref instead for `.secrets/env` |
| Bash `!` in double quotes | History expansion; use heredoc or single quotes for passwords |
| Telegram 409 conflict | Only enable `polling_enabled: true` on ONE deployment per bot token |
| Firebase JWT no fallback | When Firebase IS configured, no JWT fallback -- prevents token confusion |
| NEXT_PUBLIC_* vars | Must be in both Docker build `args` AND runtime `environment` |
| Stripe webhook raw body | Custom content type parser preserves raw Buffer for signature verification |

---

*Nova|Pulse v5.0.0 by Horizon Services*
