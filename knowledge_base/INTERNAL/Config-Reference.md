# NovaPulse Config Reference

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

NovaPulse configuration is loaded from `config/config.yaml` and overlaid with environment variables. Environment variables always take precedence over YAML values. The config is validated through Pydantic models in `src/core/config.py`.

**Config file location:** `config/config.yaml` (mounted read-only in Docker at `/app/config/config.yaml`)

**Config manager:** `ConfigManager` singleton with hot-reload via `reload()`.

---

## Configuration Sections

### `app` - Application Settings

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `name` | str | "AI Crypto Trading Bot" | -- | Display name |
| `version` | str | "3.0.0" | -- | Software version |
| `mode` | str | "paper" | `TRADING_MODE` | Trading mode: `paper` or `live` |
| `log_level` | str | "INFO" | `LOG_LEVEL` | Logging level: DEBUG/INFO/WARNING/ERROR |
| `db_path` | str | "data/trading.db" | `DB_PATH` | SQLite database file path |
| `trading_exchanges` | str | "" | `TRADING_EXCHANGES` | Comma-separated exchanges for multi-exchange mode |
| `account_id` | str | "default" | `ACCOUNT_ID` | Logical account label |
| `trading_accounts` | str | "" | `TRADING_ACCOUNTS` | Account:exchange map (e.g. "main:kraken,swing:coinbase") |

### `exchange` - Exchange Connection

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `name` | str | "kraken" | `EXCHANGE_NAME` / `ACTIVE_EXCHANGE` | Exchange name |
| `ws_url` | str | "wss://ws.kraken.com/v2" | -- | WebSocket endpoint |
| `ws_auth_url` | str | "wss://ws-auth.kraken.com/v2" | -- | Authenticated WS endpoint |
| `rest_url` | str | "https://api.kraken.com" | `EXCHANGE_REST_URL` | REST API base URL |
| `rate_limit_per_second` | int | 15 | -- | Max API requests per second |
| `max_retries` | int | 5 | -- | Max retry attempts on failure |
| `retry_base_delay` | float | 1.0 | -- | Base delay for exponential backoff (seconds) |
| `timeout` | int | 30 | -- | HTTP request timeout (seconds) |
| `maker_fee` | float | 0.0016 | `EXCHANGE_MAKER_FEE` | Maker fee rate (0.16%) |
| `taker_fee` | float | 0.0026 | `EXCHANGE_TAKER_FEE` | Taker fee rate (0.26%) |
| `post_only` | bool | false | `EXCHANGE_POST_ONLY` | Force post-only orders (maker only) |
| `limit_chase_attempts` | int | 2 | -- | Max limit order reprice attempts |
| `limit_chase_delay_seconds` | float | 2.0 | -- | Delay between chase attempts |
| `limit_fallback_to_market` | bool | true | -- | Fall back to market if limit fails |

### `trading` - Trading Parameters

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `pairs` | list | ["BTC/USD", "ETH/USD"] | -- | Trading pairs |
| `scan_interval_seconds` | int | 60 | -- | Seconds between scan cycles (min: 1) |
| `position_check_interval_seconds` | int | 2 | -- | Seconds between position management cycles |
| `warmup_bars` | int | 500 | -- | Candles to load at startup (min: 10) |
| `warmup_timeframe` | str | "1m" | -- | Base candle timeframe |
| `timeframes` | list | [1] | -- | Timeframes to analyze (in minutes) |
| `max_concurrent_positions` | int | 5 | -- | Max simultaneous open positions |
| `cooldown_seconds` | int | 300 | -- | Per-pair cooldown between trades |
| `strategy_cooldowns_seconds` | dict | {} | -- | Per-strategy cooldowns (e.g. {"keltner": 600}) |
| `event_price_move_pct` | float | 0.005 | -- | Price move % to trigger event-driven scan |
| `max_spread_pct` | float | 0.002 | -- | Max spread to allow entry |
| `use_closed_candles_only` | bool | false | -- | Drop current (incomplete) candle from analysis |
| `single_strategy_mode` | str/null | null | -- | Run only this strategy (e.g. "keltner") |
| `quiet_hours_utc` | list | [] | -- | UTC hours to skip new entries (e.g. [2,3,4,5]) |
| `max_trades_per_hour` | int | 0 | `MAX_TRADES_PER_HOUR` | Rate throttle for entries (0=disabled) |
| `candle_poll_seconds` | int | 60 | `CANDLE_POLL_SECONDS` | REST candle poll interval (fallback) |
| `canary_mode` | bool | false | `CANARY_MODE` | Enable canary mode for controlled rollout |
| `canary_pairs` | list | [] | `CANARY_PAIRS` | Restricted pair set for canary mode |
| `canary_max_pairs` | int | 2 | `CANARY_MAX_PAIRS` | Max pairs in canary mode |
| `canary_max_position_usd` | float | 100.0 | `CANARY_MAX_POSITION_USD` | Max position size in canary mode |
| `canary_max_risk_per_trade` | float | 0.005 | `CANARY_MAX_RISK_PER_TRADE` | Max risk in canary mode |
| `canary_min_confidence` | float | 0.68 | `CANARY_MIN_CONFIDENCE` | Higher confidence threshold for canary |
| `canary_min_confluence` | int | 3 | `CANARY_MIN_CONFLUENCE` | Higher confluence threshold for canary |
| `canary_scan_interval_seconds` | int | 60 | `CANARY_SCAN_INTERVAL_SECONDS` | Scan interval for canary |

### `strategies` - Strategy Configuration

Each strategy has `enabled` (bool) and `weight` (float) plus strategy-specific parameters. See Trading-Engine.md for detailed strategy configs. Strategy sub-sections:

- `strategies.keltner` (KeltnerConfig)
- `strategies.mean_reversion` (MeanReversionConfig)
- `strategies.ichimoku` (IchimokuConfig)
- `strategies.order_flow` (OrderFlowConfig)
- `strategies.trend` (TrendConfig)
- `strategies.stochastic_divergence` (StochasticDivergenceConfig)
- `strategies.volatility_squeeze` (VolatilitySqueezeConfig)
- `strategies.supertrend` (SupertrendConfig)
- `strategies.reversal` (ReversalConfig)

### `ai` - AI / Confluence Settings

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `confluence_threshold` | int | 3 | -- | Min strategies to agree for "Sure Fire" |
| `min_confidence` | float | 0.65 | -- | Min confidence for signal acceptance |
| `min_risk_reward_ratio` | float | 0.9 | -- | Min TP/SL ratio to accept trade |
| `tflite_model_path` | str | "models/trade_predictor.tflite" | -- | Path to TFLite model |
| `order_book_depth` | int | 25 | -- | Order book levels for analysis |
| `obi_threshold` | float | 0.15 | -- | OBI threshold for directional signal |
| `book_score_threshold` | float | 0.2 | -- | Book score threshold (preferred over OBI) |
| `book_score_max_age_seconds` | int | 5 | -- | Max age for book data freshness |
| `obi_counts_as_confluence` | bool | false | -- | Count OBI as a confluence vote |
| `obi_weight` | float | 0.4 | -- | Weight of synthetic OBI signal |
| `multi_timeframe_min_agreement` | int | 1 | -- | Min TFs that must agree |
| `primary_timeframe` | int | 1 | -- | Primary timeframe (drives direction) |
| `whale_threshold_usd` | float | 50000 | -- | Volume threshold for whale detection |
| `strategy_guardrails_enabled` | bool | true | -- | Enable runtime strategy auto-disable |
| `strategy_guardrails_min_trades` | int | 20 | -- | Min trades before guardrail can trigger |
| `strategy_guardrails_window_trades` | int | 30 | -- | Sliding window size for guardrail evaluation |
| `strategy_guardrails_min_win_rate` | float | 0.35 | -- | Win rate floor (below = degraded) |
| `strategy_guardrails_min_profit_factor` | float | 0.85 | -- | Profit factor floor |
| `strategy_guardrails_disable_minutes` | int | 120 | -- | How long to disable a degraded strategy |

#### `ai.session` - Session-Aware Trading

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | true | Enable per-hour confidence multiplier |
| `min_trades_per_hour` | int | 5 | Min trades for hour to have a meaningful multiplier |
| `max_boost` | float | 1.15 | Max confidence multiplier for good hours |
| `max_penalty` | float | 0.70 | Min confidence multiplier for bad hours |

#### `ai.regime` - Market Regime Detection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `adx_trend_threshold` | float | 25.0 | ADX threshold: above=trend, below=range |
| `atr_pct_high` | float | 0.02 | ATR% threshold for high volatility |
| `atr_pct_low` | float | 0.008 | ATR% threshold for low volatility |
| `trend_weight_multipliers` | dict | See defaults | Per-strategy weight mults in trend regime |
| `range_weight_multipliers` | dict | See defaults | Per-strategy weight mults in range regime |
| `high_vol_weight_multipliers` | dict | See defaults | Per-strategy weight mults in high vol |
| `low_vol_weight_multipliers` | dict | See defaults | Per-strategy weight mults in low vol |

### `risk` - Risk Management

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `max_risk_per_trade` | float | 0.02 | `MAX_RISK_PER_TRADE` | Max bankroll % risked per trade (0-0.10) |
| `max_daily_loss` | float | 0.05 | `MAX_DAILY_LOSS` | Max daily loss as % of initial bankroll (0-0.20) |
| `max_position_usd` | float | 500.0 | `MAX_POSITION_USD` | Hard cap on position size in USD |
| `initial_bankroll` | float | 10000.0 | `INITIAL_BANKROLL` | Starting bankroll (must be > 0) |
| `atr_multiplier_sl` | float | 2.0 | -- | ATR multiplier for stop loss |
| `atr_multiplier_tp` | float | 3.0 | -- | ATR multiplier for take profit |
| `trailing_activation_pct` | float | 0.015 | -- | Profit % to activate trailing stop |
| `trailing_step_pct` | float | 0.005 | -- | Trail distance as % of price (0-0.5) |
| `breakeven_activation_pct` | float | 0.01 | -- | Profit % to move stop to breakeven |
| `kelly_fraction` | float | 0.25 | -- | Kelly fraction (quarter-Kelly, 0-1.0) |
| `max_kelly_size` | float | 0.10 | -- | Max Kelly position as % of bankroll |
| `risk_of_ruin_threshold` | float | 0.01 | -- | Block trades if RoR exceeds this |
| `max_daily_trades` | int | 0 | `MAX_DAILY_TRADES` | Daily trade cap (0=unlimited, max 2000) |
| `max_total_exposure_pct` | float | 0.50 | `MAX_TOTAL_EXPOSURE_PCT` | Max total exposure as % of bankroll (0-1.0) |
| `global_cooldown_seconds_on_loss` | int | 1800 | -- | Cooldown after every loss (seconds) |

#### `risk.smart_exit` - Smart Exit Tiers

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | false | Enable multi-tier partial exits |
| `tiers` | list | See defaults | List of {pct, tp_mult} tier objects |

### `dashboard` - Dashboard Server

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `host` | str | "0.0.0.0" | `DASHBOARD_HOST` | Bind address |
| `port` | int | 8080 | `DASHBOARD_PORT` | Container port |
| `thought_feed_max` | int | 200 | -- | Max thoughts in feed |
| `refresh_interval_ms` | int | 1000 | -- | Dashboard refresh rate |
| `require_api_key_for_reads` | bool | true | `DASHBOARD_REQUIRE_API_KEY_FOR_READS` | Require auth for read endpoints |
| `allow_tenant_keys_for_control` | bool | false | `DASHBOARD_ALLOW_TENANT_KEYS_FOR_CONTROL` | Allow tenant keys for control ops |
| `rate_limit_enabled` | bool | true | `DASHBOARD_RATE_LIMIT_ENABLED` | Enable API rate limiting |
| `rate_limit_requests_per_minute` | int | 240 | `DASHBOARD_RATE_LIMIT_RPM` | Max requests per minute |
| `rate_limit_burst` | int | 60 | `DASHBOARD_RATE_LIMIT_BURST` | Burst allowance |

### `monitoring` - Health Monitoring

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `health_check_interval` | int | 30 | Seconds between health checks |
| `auto_restart` | bool | true | Enable auto-restart on failure |
| `max_restart_attempts` | int | 10 | Max restart attempts |
| `heartbeat_interval` | int | 10 | Heartbeat interval (seconds) |
| `metrics_retention_hours` | int | 72 | How long to keep metrics in DB |
| `auto_pause_on_stale_data` | bool | true | Pause on stale market data |
| `stale_data_pause_after_checks` | int | 3 | Consecutive stale checks before pause |
| `auto_pause_on_ws_disconnect` | bool | true | Pause on WS disconnect |
| `ws_disconnect_pause_after_seconds` | int | 300 | WS disconnect duration before pause |
| `auto_pause_on_consecutive_losses` | bool | true | Pause after N consecutive losses |
| `consecutive_losses_pause_threshold` | int | 4 | N consecutive losses to trigger pause |
| `auto_pause_on_drawdown` | bool | true | Pause on drawdown |
| `drawdown_pause_pct` | float | 8.0 | Drawdown % to trigger pause |
| `emergency_close_on_auto_pause` | bool | false | Close all positions on auto-pause |

### `ml` - Machine Learning

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `retrain_interval_hours` | int | 168 | `MODEL_RETRAIN_INTERVAL_HOURS` | Model retrain schedule (weekly) |
| `min_samples` | int | 10000 | -- | Min training samples |
| `epochs` | int | 50 | -- | Training epochs |
| `batch_size` | int | 64 | -- | Training batch size |
| `validation_split` | float | 0.2 | -- | Validation data fraction |
| `features` | list | See defaults | -- | Feature names for ML model |

### `tuner` - Auto Strategy Tuner

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | true | Enable weekly strategy tuning |
| `interval_hours` | int | 168 | Tuning schedule (168 = weekly) |
| `min_trades_per_strategy` | int | 15 | Min trades for tuner to evaluate |
| `weight_bounds` | list | [0.05, 0.50] | Min/max weight range |
| `auto_disable_sharpe` | float | -0.3 | Sharpe threshold to auto-disable |
| `auto_disable_min_trades` | int | 30 | Min trades before auto-disable |

### `control` - Notification Bots

#### `control.telegram`

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | -- | Enable Telegram bot |
| `token` | str | "" | `TELEGRAM_BOT_TOKEN` | Bot token |
| `chat_ids` | list | [] | `TELEGRAM_CHAT_IDS` | Allowed chat IDs |
| `polling_enabled` | bool | false | `TELEGRAM_POLLING_ENABLED` | Enable command polling |
| `send_checkins` | bool | true | -- | Send periodic check-ins |
| `checkin_interval_minutes` | int | 30 | -- | Check-in interval |

#### `control.discord`

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `DISCORD_ENABLED` | Enable Discord bot |
| `token` | str | "" | `DISCORD_TOKEN` | Bot token |
| `allowed_channel_ids` | list | [] | `DISCORD_ALLOWED_CHANNEL_IDS` | Allowed channels |
| `allowed_guild_id` | str/null | null | `DISCORD_ALLOWED_GUILD_ID` | Allowed guild |

#### `control.slack`

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `SLACK_ENABLED` | Enable Slack bot |
| `token` | str | "" | `SLACK_BOT_TOKEN` | Bot token (xoxb-...) |
| `signing_secret` | str | "" | `SLACK_SIGNING_SECRET` | Signing secret |
| `app_token` | str/null | null | `SLACK_APP_TOKEN` | Socket Mode token (xapp-...) |
| `allowed_channel_id` | str/null | null | `SLACK_ALLOWED_CHANNEL_ID` | Allowed channel |

### `billing` - Stripe Billing

#### `billing.stripe`

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `BILLING_STRIPE_ENABLED` | Enable Stripe billing |
| `secret_key` | str | "" | `STRIPE_SECRET_KEY` | Stripe secret key |
| `webhook_secret` | str | "" | `STRIPE_WEBHOOK_SECRET` | Webhook signature secret |
| `price_id` | str | "" | `STRIPE_PRICE_ID` | Legacy/default price ID |
| `price_id_pro` | str | "" | `STRIPE_PRICE_ID_PRO` | Pro plan price ID |
| `price_id_premium` | str | "" | `STRIPE_PRICE_ID_PREMIUM` | Premium plan price ID |
| `currency` | str | "usd" | `STRIPE_CURRENCY` | Billing currency |

#### `billing.tenant`

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `default_tenant_id` | str | "default" | `TENANT_ID` | Default tenant for single-tenant mode |

### `webhooks` - Signal Webhook

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `SIGNAL_WEBHOOK_ENABLED` | Enable inbound signal webhooks |
| `secret` | str | "" | `SIGNAL_WEBHOOK_SECRET` | Webhook authentication secret |
| `allowed_sources` | list | [] | `SIGNAL_WEBHOOK_ALLOWED_SOURCES` | Allowed source identifiers |
| `max_timestamp_skew_seconds` | int | 300 | `SIGNAL_WEBHOOK_MAX_TIMESTAMP_SKEW_SECONDS` | Max clock skew for webhook timestamps |

### `elasticsearch` - Analytics Pipeline

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `ELASTICSEARCH_ENABLED` | Enable ES pipeline |
| `hosts` | list | ["http://elasticsearch:9200"] | `ELASTICSEARCH_HOSTS` | ES host URLs |
| `cloud_id` | str | "" | `ES_CLOUD_ID` | Elastic Cloud ID |
| `api_key` | str | "" | `ES_API_KEY` | ES API key (base64) |
| `index_prefix` | str | "novapulse" | -- | Index name prefix |
| `bulk_size` | int | 500 | -- | Bulk insert batch size |
| `flush_interval_seconds` | float | 10.0 | -- | Flush interval |
| `buffer_maxlen` | int | 10000 | -- | Max buffer size |
| `retention_days` | dict | See defaults | -- | Per-index retention (days) |
| `poll_intervals` | dict | See defaults | -- | Data collection intervals (seconds) |
| `coingecko_api_key` | str | "" | `COINGECKO_API_KEY` | CoinGecko API key |
| `cryptopanic_api_key` | str | "" | `CRYPTOPANIC_API_KEY` | CryptoPanic API key |

### `stocks` - Stock/Options Trading

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `enabled` | bool | false | `STOCKS_ENABLED` | Enable stock trading |
| `symbols` | list | ["AAPL","MSFT","NVDA","TSLA"] | `STOCKS_SYMBOLS` | Stock symbols |
| `options_enabled` | bool | false | `STOCKS_OPTIONS_ENABLED` | Enable options trading |
| `option_symbols` | list | [] | `STOCKS_OPTION_SYMBOLS` | Option symbols |
| `scan_interval_seconds` | int | 900 | `STOCKS_SCAN_INTERVAL_SECONDS` | Scan interval |
| `max_open_positions` | int | 4 | `STOCKS_MAX_OPEN_POSITIONS` | Max open stock positions |
| `max_position_usd` | float | 500.0 | `STOCKS_MAX_POSITION_USD` | Max position size |
| `stop_loss_pct` | float | 0.02 | `STOCKS_STOP_LOSS_PCT` | Stock SL % |
| `take_profit_pct` | float | 0.04 | `STOCKS_TAKE_PROFIT_PCT` | Stock TP % |
| `db_path` | str | "data/stocks.db" | `STOCKS_DB_PATH` | Stock DB path |

See `src/core/config.py` for additional stock and Alpaca/Polygon configuration fields.

---

## Environment Variables (Auth / Secrets)

These are NOT in config.yaml -- they are set exclusively via `.env` or environment:

| Variable | Required | Description |
|----------|----------|-------------|
| `KRAKEN_API_KEY` | Live mode | Kraken API key |
| `KRAKEN_API_SECRET` | Live mode | Kraken API secret |
| `COINBASE_API_KEY` | Coinbase mode | Coinbase CDP key name |
| `COINBASE_API_SECRET` | Coinbase mode | Coinbase private key PEM |
| `DASHBOARD_ADMIN_KEY` | Live mode | Admin API key (required in live) |
| `DASHBOARD_READ_KEY` | Optional | Read-only API key |
| `DASHBOARD_SESSION_SECRET` | Live mode | Session signing secret (required in live) |
| `DASHBOARD_ADMIN_USERNAME` | Optional | Web login username (default: "admin") |
| `DASHBOARD_ADMIN_PASSWORD` | Optional | Web login password (plaintext) |
| `DASHBOARD_ADMIN_PASSWORD_HASH` | Live mode | Bcrypt hash of admin password (required in live) |
| `DASHBOARD_SESSION_TTL_SECONDS` | Optional | Session lifetime (default: 43200 = 12h) |
| `BOT_UID` | Docker | Container user ID (default: 1000) |
| `BOT_GID` | Docker | Container group ID (default: 1000) |
| `HOST_PORT` | Docker | Host port binding (default: 127.0.0.1:8090) |

---

## Config Hot-Reload

The ConfigManager supports hot-reload:

```python
from src.core.config import ConfigManager
cm = ConfigManager()
cm.reload()  # Re-reads config.yaml + env vars
```

The auto-tuner uses `save_to_yaml()` to persist weight changes back to `config/config.yaml` using `ruamel.yaml` to preserve comments and formatting.

---

## Validation Rules

Pydantic validators enforce:

- `max_risk_per_trade`: must be between 0 and 0.10
- `max_daily_loss`: must be between 0 and 0.20
- `initial_bankroll`: must be > 0 (prevents div-by-zero)
- `kelly_fraction`: must be in (0.0, 1.0]
- `trailing_step_pct`: must be in (0.0, 0.5)
- `scan_interval_seconds`: must be >= 1 (prevents tight infinite loop)
- `warmup_bars`: must be >= 10
- `max_daily_trades`: must be between 0 and 2000
- `max_total_exposure_pct`: must be between 0 and 1.0
- Stock-specific validators for hold days, TP > SL, non-negative costs
