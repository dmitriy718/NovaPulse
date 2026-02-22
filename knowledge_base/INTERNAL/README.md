# NovaPulse Internal Documentation

**Product:** NovaPulse AI Crypto Trading Bot
**Version:** 4.0.0
**Audience:** Horizon Services support team, developers, and DevOps engineers
**Last Updated:** 2026-02-22

---

## Table of Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [Architecture](Architecture.md) | System overview, component map, data flow, deployment model |
| 2 | [Trading-Engine](Trading-Engine.md) | Deep dive into 9 strategies, confluence engine, adaptive weighting, regime detection, MTF |
| 3 | [Risk-Management](Risk-Management.md) | Kelly Criterion sizing, ATR stops, trailing/breakeven, circuit breakers, smart exit |
| 4 | [Exchange-Integration](Exchange-Integration.md) | Kraken WS v2, Coinbase Advanced Trade, exception hierarchy, order flow, reconnection |
| 5 | [Config-Reference](Config-Reference.md) | Complete config.yaml field reference with environment variable overrides |
| 6 | [Operations](Operations.md) | Day-to-day Docker deployment, log inspection, DB queries, mode transitions |
| 7 | [Runbooks](Runbooks.md) | Step-by-step incident response procedures |
| 8 | [Support-Triage](Support-Triage.md) | Customer issue triage by priority level |
| 9 | [Security](Security.md) | Authentication, rate limiting, brute-force protection, multi-tenant isolation |
| 10 | [Data-Formats](Data-Formats.md) | SQLite schema, REST/WS message formats, structlog JSON, ES indexes |
| 11 | [Credential-Rotation](Credential-Rotation.md) | Zero-downtime key rotation for all external services |
| 12 | [FAQ](FAQ.md) | Internal frequently asked questions |

---

## Quick Reference

| Item | Value |
|------|-------|
| Main entry point | `main.py` |
| Dashboard port (container) | 8080 |
| Dashboard port (host default) | 8090 |
| Default database | `data/trading.db` (SQLite, WAL mode) |
| Config file | `config/config.yaml` |
| Docker service | `trading-bot` (container name: `novapulse`) |
| Python versions | 3.11, 3.12, 3.13 |
| Primary exchange | Kraken (WS v2 + REST) |
| Secondary exchange | Coinbase (Advanced Trade REST + WS) |
| Strategies | 9 (Keltner, Mean Reversion, Ichimoku, Order Flow, Trend, Stochastic Divergence, Volatility Squeeze, Supertrend, Reversal) |
| Trading modes | `paper` (default), `live` |
| Multi-tenant | Yes (Stripe billing, tenant API keys, DB isolation via tenant_id) |

---

## Architecture at a Glance

```
Market Data (Kraken WS / Coinbase WS)
         |
    BotEngine (main.py / engine.py)
         |
    ConfluenceDetector (9 strategies)
         |
    AI Predictor (TFLite / Continuous Learner)
         |
    RiskManager (Kelly sizing, stops, circuit breakers)
         |
    TradeExecutor (limit entry, market exit)
         |
    Exchange REST API (Kraken / Coinbase)
```

---

## Source Code Layout

```
NovaPulse/
  main.py                  # Entry point, lifecycle management
  config/config.yaml       # Runtime configuration
  src/
    core/
      engine.py            # BotEngine orchestrator
      config.py            # Pydantic config models
      database.py          # SQLite WAL manager
      control_router.py    # Pause/resume/close_all router
      logger.py            # Structlog setup
      structures.py        # RingBuffer for market data
      multi_engine.py      # Multi-exchange hub
    ai/
      confluence.py        # 9-strategy confluence detector
      predictor.py         # TFLite inference
      order_book.py        # Order book microstructure analysis
      session_analyzer.py  # Per-hour confidence multiplier
    execution/
      executor.py          # Trade lifecycle management
      risk_manager.py      # Position sizing and risk controls
    exchange/
      kraken_ws.py         # Kraken WebSocket v2 client
      kraken_rest.py       # Kraken REST API client
      coinbase_rest.py     # Coinbase Advanced Trade REST
      coinbase_ws.py       # Coinbase WebSocket client
      market_data.py       # MarketDataCache (candle ring buffers)
      exceptions.py        # Typed exchange exception hierarchy
    strategies/
      keltner.py           # Keltner Channel rebound
      mean_reversion.py    # Bollinger Band extremes
      ichimoku.py          # Ichimoku Cloud crossovers
      order_flow.py        # Order book microstructure
      trend.py             # EMA crossover + ADX
      stochastic_divergence.py  # Stochastic + divergence
      volatility_squeeze.py     # TTM Squeeze concept
      supertrend.py        # ATR-based adaptive trend
      reversal.py          # Extreme RSI + confirmation
    ml/
      trainer.py           # TFLite model training
      continuous_learner.py # Online SGD learner
      strategy_tuner.py    # Weekly auto-tuner
    api/
      server.py            # FastAPI dashboard
    billing/
      stripe_service.py    # Stripe subscription management
    utils/
      indicators.py        # Technical indicator library
      telegram.py          # Telegram bot
      discord_bot.py       # Discord bot
      slack_bot.py         # Slack bot
    data/
      es_client.py         # Elasticsearch client
      ingestion.py         # External data collection
    stocks/
      swing_engine.py      # Stock/options swing trading
  tests/                   # Test suite
  data/                    # SQLite databases (Docker volume)
  logs/                    # Log files
  models/                  # ML model artifacts
```
