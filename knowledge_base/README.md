# Nova|Pulse by Horizon Services -- Knowledge Base

**Version:** 5.0.0
**Last updated:** 2026-03-02

---

## About Nova|Pulse

**Nova|Pulse** is an AI-powered autonomous trading platform built and operated by **Horizon Services LLC**. It consists of two integrated systems:

- **NovaPulse Trading Bot** -- A Python asyncio engine that runs 12 AI strategies in parallel across cryptocurrency (Kraken, Coinbase) and US stock markets (Alpaca/Polygon). It uses a confluence engine, institutional-grade risk management, and machine learning to trade 24/7.

- **Horizon Web Platform** -- A Next.js web application at [horizonsvc.com](https://horizonsvc.com) providing account management, subscription billing (Stripe), a real-time performance dashboard, gamification, a signal scanner, email notifications, and support ticketing.

Together, they deliver a complete trading experience: the bot does the trading, the platform lets you monitor, understand, and manage everything from any device.

---

## Knowledge Base Structure

This knowledge base is organized into two sections:

- **[CLIENT/](CLIENT/README.md)** -- Documentation for subscribers and end users. Plain-language guides covering setup, features, strategies, risk management, dashboards, billing, and troubleshooting.

- **[INTERNAL/](INTERNAL/README.md)** -- Documentation for developers, support engineers, and operators. Technical implementation details, architecture, API references, database schemas, deployment guides, and runbooks.

---

## Client Documentation

| # | Guide | What It Covers |
|---|-------|----------------|
| 1 | [Getting Started](CLIENT/Getting-Started.md) | Account creation, plan selection, exchange setup, bot connection, first scan |
| 2 | [Bot Dashboard Walkthrough](CLIENT/Nova-Dashboard-Walkthrough.md) | Every panel, metric, and button on the NovaPulse built-in command center |
| 3 | [Horizon Dashboard](CLIENT/Horizon-Dashboard.md) | The horizonsvc.com web dashboard -- connecting your bot, live monitoring, comparison to bot dashboard |
| 4 | [Controls: Pause, Resume, Kill](CLIENT/Controls-Pause-Resume-Kill.md) | How to control trading -- pause, resume, close all positions, emergency stop |
| 5 | [Understanding Metrics](CLIENT/Understanding-Metrics.md) | Plain-language explanations of every performance number you will see |
| 6 | [Trading Strategies](CLIENT/Trading-Strategies.md) | How the twelve AI strategies work and why confluence matters |
| 7 | [Risk and Safety](CLIENT/Risk-Safety.md) | Every layer of protection keeping your capital safe |
| 8 | [Smart Exit System](CLIENT/Smart-Exit-System.md) | Adaptive multi-tier exits, trailing stops, and time-based position management |
| 9 | [Multi-Exchange Trading](CLIENT/Multi-Exchange-Trading.md) | How Nova|Pulse trades across Kraken, Coinbase, and stock markets simultaneously |
| 10 | [Stock Trading](CLIENT/Stock-Trading.md) | Swing trading US equities with dynamic universe scanning |
| 11 | [AI and ML Features](CLIENT/AI-ML-Features.md) | How artificial intelligence and machine learning improve your trading |
| 12 | [Advanced Features (v5.0)](CLIENT/Advanced-Features.md) | Event calendar, lead-lag, regime prediction, structural stops, ensemble ML, and more |
| 13 | [Notifications (Bot)](CLIENT/Notifications.md) | Setting up Telegram, Discord, and Slack alerts and commands |
| 14 | [Email Notifications (Horizon)](CLIENT/Horizon-Email-Notifications.md) | Email notification categories, preferences, scheduled reports, unsubscribe system |
| 15 | [Configuration Guide](CLIENT/Configuration-Guide.md) | Adjusting settings, pairs, risk levels, and strategy parameters |
| 16 | [Horizon Trading Features](CLIENT/Horizon-Trading-Features.md) | Overview of the NovaPulse engine as presented on the Horizon platform |
| 17 | [Scanner and Signals](CLIENT/Horizon-Scanner-Signals.md) | Pro-only live trading signals scanner and public signal feed |
| 18 | [Gamification](CLIENT/Horizon-Gamification.md) | Achievements, milestones, ranks, levels, XP, streaks |
| 19 | [Security and Privacy](CLIENT/Security-Privacy.md) | How your account, data, and API keys are protected across both systems |
| 20 | [Troubleshooting](CLIENT/Troubleshooting.md) | Common issues with the bot, dashboard, billing, and email -- and how to fix them |
| 21 | [FAQ](CLIENT/FAQ.md) | Frequently asked questions about the trading bot |
| 22 | [Billing and Plans](CLIENT/Billing-Plans.md) | Subscription tiers, hosting options, Stripe billing, refund policy |
| 23 | [Contact and Support](CLIENT/Contact-Support.md) | How to reach us, ticket system, response times, escalation |

---

## Internal Documentation

| # | Document | What It Covers |
|---|----------|----------------|
| | **NovaPulse Trading Bot** | |
| 1 | [Architecture](INTERNAL/Architecture.md) | System overview, component map, data flow, deployment model, background tasks |
| 2 | [Trading Engine](INTERNAL/Trading-Engine.md) | BotEngine orchestrator, 12 strategies, confluence, adaptive weighting, regime detection, MTF |
| 3 | [Confluence Engine](INTERNAL/Confluence-Engine.md) | Deep dive into confluence detector, family diversity scoring, opposition penalty, OBI votes |
| 4 | [Risk Management](INTERNAL/Risk-Management.md) | Kelly sizing, ATR stops, trailing/breakeven, circuit breakers, smart exit, structural stops, liquidity |
| 5 | [Adaptive Exits](INTERNAL/Adaptive-Exits.md) | Time-based exit tightening, vol-regime trailing stops, smart exit tiers |
| 6 | [Exchange Integration](INTERNAL/Exchange-Integration.md) | Kraken WS v2, Coinbase Advanced Trade, exception hierarchy, order flow, reconnection |
| 7 | [WebSocket Integration](INTERNAL/WebSocket-Integration.md) | Kraken WS v2 and Coinbase WS implementation details, subscription management |
| 8 | [Multi-Engine Architecture](INTERNAL/Multi-Engine-Architecture.md) | MultiEngineHub, MultiControlRouter, priority scheduler, cross-engine coordination |
| 9 | [Stock Swing Engine](INTERNAL/Stock-Swing-Engine.md) | Stock trading: Polygon data, Alpaca execution, universe scanner, swing strategy |
| 10 | [Config Reference](INTERNAL/Config-Reference.md) | Complete config.yaml field reference with environment variable overrides |
| 11 | [Database Schema (Bot)](INTERNAL/Database-Schema.md) | SQLite tables, WAL mode, migrations, query patterns |
| 12 | [Data Formats](INTERNAL/Data-Formats.md) | REST/WS message formats, structlog JSON, Elasticsearch indexes |
| 13 | [ML Training Pipeline](INTERNAL/ML-Training-Pipeline.md) | TFLite training, continuous learner, auto-tuner, cross-exchange aggregation |
| 14 | [Indicator Library](INTERNAL/Indicator-Library.md) | Technical indicators, IndicatorCache, vectorized computation |
| 15 | [Global Risk Aggregation](INTERNAL/Global-Risk-Aggregation.md) | Cross-engine exposure tracking via GlobalRiskAggregator singleton |
| 16 | [Correlation Sizing](INTERNAL/Correlation-Sizing.md) | Pearson correlation-based position size reduction |
| 17 | [Funding Rate Integration](INTERNAL/Funding-Rate-Integration.md) | Kraken Futures funding rate client and strategy |
| 18 | [Market Structure Strategy](INTERNAL/Market-Structure-Strategy.md) | Swing-based trend structure detection and pullback entries |
| 19 | [VWAP Strategy](INTERNAL/VWAP-Strategy.md) | VWAP momentum alpha strategy implementation |
| 20 | [Advanced Features (Bot)](INTERNAL/Advanced-Features.md) | v5.0 features: event calendar, lead-lag, regime predictor, on-chain, structural stops, anomaly detector, ensemble ML, Bayesian optimizer |
| 21 | [Elasticsearch Pipeline](INTERNAL/Elasticsearch-Pipeline.md) | ES client, ingestion, enrichment, index management, external data |
| 22 | [Security (Bot)](INTERNAL/Security.md) | Authentication, rate limiting, brute-force protection, CORS, CSP, CSRF, secrets management |
| 23 | [Operations](INTERNAL/Operations.md) | Docker deployment, log inspection, DB queries, mode transitions, rsync deploy |
| 24 | [Runbooks](INTERNAL/Runbooks.md) | Step-by-step incident response procedures |
| 25 | [Support Triage](INTERNAL/Support-Triage.md) | Customer issue triage by priority level |
| 26 | [Credential Rotation](INTERNAL/Credential-Rotation.md) | Zero-downtime key rotation for all external services |
| 27 | [Dashboard Integration](INTERNAL/Dashboard-Integration.md) | horizonsvc.com proxy: Caddy, bot_connections, Fastify proxy routes, SSRF protection |
| 28 | [FAQ (Bot Internal)](INTERNAL/FAQ.md) | Internal frequently asked questions about the bot |
| | **Horizon Web Platform** | |
| 29 | [Horizon Architecture](INTERNAL/Horizon-Architecture.md) | System overview, tech stack, service topology, data flow diagrams |
| 30 | [Horizon API Reference](INTERNAL/Horizon-API-Reference.md) | All API endpoints with request/response formats, authentication, error codes |
| 31 | [Horizon Authentication](INTERNAL/Horizon-Authentication.md) | Firebase setup, token verification flow, account lockout, login tracking |
| 32 | [Horizon Billing (Stripe)](INTERNAL/Horizon-Billing-Stripe.md) | Stripe integration, checkout flow, webhook handling, entitlement management |
| 33 | [Horizon Bot Integration](INTERNAL/Horizon-Bot-Integration.md) | Bot proxy architecture, SSRF protection, connection lifecycle, bot monitor |
| 34 | [Horizon Database Schema](INTERNAL/Horizon-Database-Schema.md) | PostgreSQL tables, columns, relationships, indexes, migrations |
| 35 | [Horizon Deployment](INTERNAL/Horizon-Deployment.md) | Docker Compose, Nginx, Ansible, environment variables, CI/CD |
| 36 | [Horizon Email System](INTERNAL/Horizon-Email-System.md) | SMTP config, template system, preference checking, unsubscribe, bot monitor |
| 37 | [Horizon SEO Guide](INTERNAL/Horizon-SEO-Guide.md) | Metadata, JSON-LD, sitemap, robots.txt, Open Graph/Twitter cards |
| 38 | [Horizon Security](INTERNAL/Horizon-Security.md) | CSP, rate limiting, CORS, HMAC tokens, input validation, SSRF prevention |

---

## Quick Links

| Action | Where to Go |
|---|---|
| Sign up | [horizonsvc.com/signup](https://horizonsvc.com/signup) |
| Log in | [horizonsvc.com/auth](https://horizonsvc.com/auth) |
| Dashboard | [horizonsvc.com/dashboard](https://horizonsvc.com/dashboard) |
| Settings | [horizonsvc.com/settings](https://horizonsvc.com/settings) |
| Pricing | [horizonsvc.com/pricing](https://horizonsvc.com/pricing) |
| Support | [horizonsvc.com/support](https://horizonsvc.com/support) |
| Academy | [horizonsvc.com/academy](https://horizonsvc.com/academy) |

---

*Nova|Pulse v5.0.0 by Horizon Services -- Built for traders who value discipline, transparency, and control.*
