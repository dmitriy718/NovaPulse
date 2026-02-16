# Config Reference

Config sources:
- YAML: `config/config.yaml`
- Environment overrides: `.env` (see `.env.example`) overlaid by `src/core/config.py`.

## Common settings

App:
- `app.mode`: `paper` or `live`
- `app.db_path`: SQLite DB path

Exchange:
- `exchange.name`: `kraken` or `coinbase`
- Fees: `exchange.maker_fee`, `exchange.taker_fee`
- Execution behavior: `exchange.post_only`, `exchange.limit_chase_attempts`, `exchange.limit_fallback_to_market`

Trading:
- `trading.pairs`: list of pairs (`BTC/USD`, etc.)
- `trading.scan_interval_seconds`: scan cadence (scan queue is event-driven + fallback timeout)
- `trading.position_check_interval_seconds`: stop management cadence
- `trading.timeframes`: confluence timeframes (e.g. `[1, 5, 15]`)
- `trading.max_spread_pct`: spread filter (see `MarketDataCache.get_spread`)
- `trading.use_closed_candles_only`: ignores in-progress candle for strategy analysis
- `trading.strategy_cooldowns_seconds`: cooldown per strategy
- `trading.single_strategy_mode`: isolate a single strategy for debugging

AI:
- `ai.confluence_threshold`: minimum strategies in agreement
- `ai.min_confidence`: minimum confidence to execute
- `ai.obi_counts_as_confluence`: when true, order book score can count as confluence
- `ai.book_score_max_age_seconds`: freshness threshold for book score
- Multi-timeframe: `ai.multi_timeframe_min_agreement`, `ai.primary_timeframe`
- Regime multipliers: `ai.regime.*`

Risk:
- `risk.max_risk_per_trade`: fixed fractional cap
- `risk.max_daily_loss`: blocks new entries after daily drawdown threshold
- `risk.max_position_usd`: absolute cap
- `risk.kelly_fraction` and `risk.max_kelly_size`: Kelly sizing cap
- `risk.risk_of_ruin_threshold`: blocks trading if RoR exceeds threshold
- `risk.global_cooldown_seconds_on_loss`: global cooldown after a loss

Control:
- `control.telegram`: `token` and `chat_ids` allowlist
- `control.web.enabled`: enables dashboard control endpoints

Billing:
- `billing.stripe.enabled`: enable Stripe integration
- `billing.tenant.default_tenant_id`: default tenant id for single-tenant mode

## Environment variables (high value)

See `.env.example` for the full set.

Important:
- `DASHBOARD_SECRET_KEY`: admin key for control endpoints (required in live mode).
- `DB_PATH`: database path override.
- `ACTIVE_EXCHANGE` or `TRADING_EXCHANGES`: single or multi-exchange mode.

Known constraint:
- Python 3.13 is currently blocked; use Python 3.11 or 3.12.

