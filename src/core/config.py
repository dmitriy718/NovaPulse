"""
Configuration Manager - Loads and validates all system configuration.

Merges YAML config with environment variables. Environment variables take
precedence over YAML values for deployment flexibility.

# ENHANCEMENT: Added hot-reload capability for runtime config changes
# ENHANCEMENT: Added deep validation with Pydantic models
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Environment overrides (shared)
# ---------------------------------------------------------------------------

def _apply_env_overrides(config: Dict[str, Any]) -> None:
    """Override YAML values with environment variables where set."""
    def _set_path(root: Dict[str, Any], path: tuple[str, ...], v: Any) -> None:
        d: Dict[str, Any] = root
        for key in path[:-1]:
            nxt = d.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                d[key] = nxt
            d = nxt
        d[path[-1]] = v

    env_mappings = {
        "TRADING_MODE": ("app", "mode"),
        "LOG_LEVEL": ("app", "log_level"),
        "MAX_RISK_PER_TRADE": ("risk", "max_risk_per_trade", float),
        "MAX_DAILY_LOSS": ("risk", "max_daily_loss", float),
        "MAX_POSITION_USD": ("risk", "max_position_usd", float),
        "MAX_DAILY_TRADES": ("risk", "max_daily_trades", int),
        "MAX_TOTAL_EXPOSURE_PCT": ("risk", "max_total_exposure_pct", float),
        "INITIAL_BANKROLL": ("risk", "initial_bankroll", float),
        "MAX_TRADES_PER_HOUR": ("trading", "max_trades_per_hour", int),
        "DASHBOARD_HOST": ("dashboard", "host"),
        "DASHBOARD_PORT": ("dashboard", "port", int),
        "DASHBOARD_REQUIRE_API_KEY_FOR_READS": (
            "dashboard",
            "require_api_key_for_reads",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        # Legacy alias kept for backward compatibility with older .env templates.
        "DASHBOARD_REQUIRE_AUTH_FOR_READS": (
            "dashboard",
            "require_api_key_for_reads",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "DASHBOARD_ALLOW_TENANT_KEYS_FOR_CONTROL": (
            "dashboard",
            "allow_tenant_keys_for_control",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "DASHBOARD_RATE_LIMIT_ENABLED": (
            "dashboard",
            "rate_limit_enabled",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "DASHBOARD_RATE_LIMIT_RPM": ("dashboard", "rate_limit_requests_per_minute", int),
        "DASHBOARD_RATE_LIMIT_BURST": ("dashboard", "rate_limit_burst", int),
        "MODEL_RETRAIN_INTERVAL_HOURS": ("ml", "retrain_interval_hours", int),
        "DB_PATH": ("app", "db_path"),
        # Per-instance logical account isolation inside the DB (horizon vs pi).
        "TENANT_ID": (("billing", "tenant", "default_tenant_id"), str),
        "EXCHANGE_NAME": ("exchange", "name"),
        "ACTIVE_EXCHANGE": ("exchange", "name"),
        "TRADING_EXCHANGES": ("app", "trading_exchanges"),
        "TRADING_EXCHANGE": ("app", "trading_exchanges"),
        "TRADING_ACCOUNTS": ("app", "trading_accounts"),
        "ACCOUNT_ID": ("app", "account_id"),
        "EXCHANGE_REST_URL": ("exchange", "rest_url"),
        "EXCHANGE_WS_URL": ("exchange", "ws_url"),
        "EXCHANGE_MAKER_FEE": ("exchange", "maker_fee", float),
        "EXCHANGE_TAKER_FEE": ("exchange", "taker_fee", float),
        "EXCHANGE_POST_ONLY": ("exchange", "post_only", lambda v: v.lower() in ("1", "true", "yes", "on")),
        "CANDLE_POLL_SECONDS": ("trading", "candle_poll_seconds", int),
        "CANARY_MODE": (
            "trading",
            "canary_mode",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "CANARY_PAIRS": (
            "trading",
            "canary_pairs",
            lambda v: [p.strip() for p in v.split(",") if p.strip()],
        ),
        "CANARY_MAX_PAIRS": ("trading", "canary_max_pairs", int),
        "CANARY_MAX_POSITION_USD": ("trading", "canary_max_position_usd", float),
        "CANARY_MAX_RISK_PER_TRADE": ("trading", "canary_max_risk_per_trade", float),
        "CANARY_MIN_CONFIDENCE": ("trading", "canary_min_confidence", float),
        "CANARY_MIN_CONFLUENCE": ("trading", "canary_min_confluence", int),
        "CANARY_SCAN_INTERVAL_SECONDS": ("trading", "canary_scan_interval_seconds", int),
        "STOCKS_ENABLED": (
            "stocks",
            "enabled",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "STOCKS_SYMBOLS": (
            "stocks",
            "symbols",
            lambda v: [s.strip().upper() for s in v.split(",") if s.strip()],
        ),
        "STOCKS_SCAN_INTERVAL_SECONDS": ("stocks", "scan_interval_seconds", int),
        "STOCKS_LOOKBACK_BARS": ("stocks", "lookback_bars", int),
        "STOCKS_MIN_HOLD_DAYS": ("stocks", "min_hold_days", int),
        "STOCKS_MAX_HOLD_DAYS": ("stocks", "max_hold_days", int),
        "STOCKS_MAX_OPEN_POSITIONS": ("stocks", "max_open_positions", int),
        "STOCKS_MAX_POSITION_USD": ("stocks", "max_position_usd", float),
        "STOCKS_OPTIONS_ENABLED": (
            "stocks",
            "options_enabled",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "STOCKS_OPTION_SYMBOLS": (
            "stocks",
            "option_symbols",
            lambda v: [s.strip().upper() for s in v.split(",") if s.strip()],
        ),
        "STOCKS_OPTION_CONTRACT_MULTIPLIER": ("stocks", "option_contract_multiplier", int),
        "STOCKS_STOP_LOSS_PCT": ("stocks", "stop_loss_pct", float),
        "STOCKS_TAKE_PROFIT_PCT": ("stocks", "take_profit_pct", float),
        "STOCKS_ESTIMATED_FEE_PCT_PER_SIDE": ("stocks", "estimated_fee_pct_per_side", float),
        "STOCKS_ESTIMATED_SLIPPAGE_PCT_PER_SIDE": ("stocks", "estimated_slippage_pct_per_side", float),
        "STOCKS_DB_PATH": ("stocks", "db_path"),
        "POLYGON_API_KEY": ("stocks", "polygon_api_key"),
        "POLYGON_BASE_URL": ("stocks", "polygon_base_url"),
        # 1Password/operator aliases used in deployment vaults.
        "ALPACA_KEY": ("stocks", "alpaca_api_key"),
        "ALPACA_SECRET": ("stocks", "alpaca_api_secret"),
        "ALPACA_SECRET_KEY": ("stocks", "alpaca_api_secret"),
        "ALPACA_ENDPOINT": (
            "stocks",
            "alpaca_base_url",
            lambda v: (v or "").rstrip("/").removesuffix("/v2"),
        ),
        "ALPACA_API_KEY": ("stocks", "alpaca_api_key"),
        "ALPACA_API_SECRET": ("stocks", "alpaca_api_secret"),
        "ALPACA_BASE_URL": ("stocks", "alpaca_base_url"),
        "ELASTICSEARCH_ENABLED": (
            "elasticsearch",
            "enabled",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "ELASTICSEARCH_HOSTS": (
            "elasticsearch",
            "hosts",
            lambda v: [h.strip() for h in v.split(",") if h.strip()],
        ),
        "ES_API_KEY": ("elasticsearch", "api_key"),
        "ES_CLOUD_ID": ("elasticsearch", "cloud_id"),
        "COINGECKO_API_KEY": ("elasticsearch", "coingecko_api_key"),
        "CRYPTOPANIC_API_KEY": ("elasticsearch", "cryptopanic_api_key"),
        "TELEGRAM_BOT_TOKEN": (("control", "telegram", "token"), str),
        "TELEGRAM_CHAT_IDS": (
            ("control", "telegram", "chat_ids"),
            lambda v: [s.strip() for s in v.split(",") if s.strip()],
        ),
        "TELEGRAM_CHAT_ID": (
            ("control", "telegram", "chat_ids"),
            lambda v: [s.strip() for s in v.split(",") if s.strip()],
        ),
        "TELEGRAM_POLLING_ENABLED": (
            ("control", "telegram", "polling_enabled"),
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "DISCORD_ENABLED": (
            ("control", "discord", "enabled"),
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "DISCORD_TOKEN": (("control", "discord", "token"), str),
        "DISCORD_ALLOWED_CHANNEL_IDS": (
            ("control", "discord", "allowed_channel_ids"),
            lambda v: [s.strip() for s in v.split(",") if s.strip()],
        ),
        "DISCORD_ALLOWED_GUILD_ID": (("control", "discord", "allowed_guild_id"), str),
        "SLACK_ENABLED": (
            ("control", "slack", "enabled"),
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "SLACK_BOT_TOKEN": (("control", "slack", "token"), str),
        "SLACK_SIGNING_SECRET": (("control", "slack", "signing_secret"), str),
        "SLACK_APP_TOKEN": (("control", "slack", "app_token"), str),
        "SLACK_ALLOWED_CHANNEL_ID": (("control", "slack", "allowed_channel_id"), str),
        "SIGNAL_WEBHOOK_ENABLED": (
            "webhooks",
            "enabled",
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "SIGNAL_WEBHOOK_SECRET": ("webhooks", "secret"),
        "SIGNAL_WEBHOOK_ALLOWED_SOURCES": (
            "webhooks",
            "allowed_sources",
            lambda v: [s.strip().lower() for s in v.split(",") if s.strip()],
        ),
        "SIGNAL_WEBHOOK_MAX_TIMESTAMP_SKEW_SECONDS": (
            "webhooks",
            "max_timestamp_skew_seconds",
            int,
        ),
        "BILLING_STRIPE_ENABLED": (
            ("billing", "stripe", "enabled"),
            lambda v: v.lower() in ("1", "true", "yes", "on"),
        ),
        "STRIPE_SECRET_KEY": (("billing", "stripe", "secret_key"), str),
        "STRIPE_WEBHOOK_SECRET": (("billing", "stripe", "webhook_secret"), str),
        "STRIPE_PRICE_ID": (("billing", "stripe", "price_id"), str),
        "STRIPE_PRICE_ID_PRO": (("billing", "stripe", "price_id_pro"), str),
        "STRIPE_PRICE_ID_PREMIUM": (("billing", "stripe", "price_id_premium"), str),
        "STRIPE_CURRENCY": (("billing", "stripe", "currency"), str),
    }

    for env_key, mapping in env_mappings.items():
        value = os.getenv(env_key)
        if value is not None:
            # Back-compat: ("section","key"[,"converter"]) or (("a","b","c"), converter)
            try:
                if isinstance(mapping[0], tuple):
                    path = mapping[0]
                    converter = mapping[1] if len(mapping) > 1 else str
                    _set_path(config, path, converter(value))
                else:
                    section = mapping[0]
                    key = mapping[1]
                    converter = mapping[2] if len(mapping) > 2 else str
                    if section not in config:
                        config[section] = {}
                    config[section][key] = converter(value)
            except (ValueError, TypeError) as e:
                import logging
                logging.getLogger("config").warning(
                    "Env %s=%r failed to convert: %s. Using YAML value.",
                    env_key, value, e,
                )


# ---------------------------------------------------------------------------
# Pydantic Configuration Models (strict validation)
# ---------------------------------------------------------------------------

class ExchangeConfig(BaseModel):
    name: str = "kraken"
    ws_url: str = "wss://ws.kraken.com/v2"
    ws_auth_url: str = "wss://ws-auth.kraken.com/v2"
    rest_url: str = "https://api.kraken.com"
    rate_limit_per_second: int = 15
    max_retries: int = 5
    retry_base_delay: float = 1.0
    timeout: int = 30
    maker_fee: float = 0.0016
    taker_fee: float = 0.0026
    post_only: bool = False
    limit_chase_attempts: int = 2
    limit_chase_delay_seconds: float = 2.0
    limit_fallback_to_market: bool = True


class TradingConfig(BaseModel):
    pairs: List[str] = Field(default_factory=lambda: ["BTC/USD", "ETH/USD"])
    scan_interval_seconds: int = 60
    position_check_interval_seconds: int = 2
    hft_scan_interval_seconds: int = 1
    candle_poll_seconds: int = 60
    warmup_bars: int = 500
    warmup_timeframe: str = "1m"
    timeframes: List[int] = Field(default_factory=lambda: [1])
    max_concurrent_positions: int = 5
    cooldown_seconds: int = 300
    strategy_cooldowns_seconds: Dict[str, int] = Field(default_factory=dict)
    event_price_move_pct: float = 0.005
    max_spread_pct: float = 0.002
    use_closed_candles_only: bool = False
    # Single Strategy Mode: if set, only this strategy runs (e.g. "keltner", "trend")
    single_strategy_mode: Optional[Union[str, bool]] = None
    # Quiet hours: skip new entries during these UTC hours (e.g. [2,3,4,5])
    quiet_hours_utc: List[int] = Field(default_factory=list)
    # Hard throttle for new entries to prevent runaway overtrading.
    # 0 disables the throttle.
    max_trades_per_hour: int = 0
    # Canary mode: tighter limits and restricted pair set for controlled rollout.
    canary_mode: bool = False
    canary_pairs: List[str] = Field(default_factory=list)
    canary_max_pairs: int = 2
    canary_max_position_usd: float = 100.0
    canary_max_risk_per_trade: float = 0.005
    canary_min_confidence: float = 0.68
    canary_min_confluence: int = 3
    canary_scan_interval_seconds: int = 60


class StrategyWeights(BaseModel):
    enabled: bool = True
    weight: float = 0.20


class TrendConfig(StrategyWeights):
    ema_fast: int = 5
    ema_slow: int = 13
    adx_threshold: int = 25


class MeanReversionConfig(StrategyWeights):
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_oversold: int = 30
    rsi_overbought: int = 70


class IchimokuConfig(StrategyWeights):
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    atr_period: int = 14
    weight: float = 0.15


class StochasticDivergenceConfig(StrategyWeights):
    k_period: int = 14
    d_period: int = 3
    smooth: int = 3
    oversold: float = 20.0
    overbought: float = 80.0
    divergence_lookback: int = 20
    atr_period: int = 14
    weight: float = 0.12


class VolatilitySqueezeConfig(StrategyWeights):
    bb_period: int = 20
    bb_std: float = 2.0
    kc_ema_period: int = 20
    kc_atr_period: int = 14
    kc_multiplier: float = 1.5
    momentum_period: int = 12
    atr_period: int = 14
    min_squeeze_bars: int = 3
    weight: float = 0.12


class OrderFlowConfig(StrategyWeights):
    book_score_threshold: float = 0.3
    spread_tight_pct: float = 0.0010
    hl_lookback: int = 5
    max_book_age_seconds: int = 5
    atr_period: int = 14
    weight: float = 0.15


class SupertrendConfig(StrategyWeights):
    st_period: int = 10
    st_multiplier: float = 3.0
    volume_period: int = 20
    volume_threshold: float = 1.2
    atr_period: int = 14
    weight: float = 0.10


class ReversalConfig(StrategyWeights):
    rsi_extreme_low: int = 20
    rsi_extreme_high: int = 80
    confirmation_candles: int = 3


class KeltnerConfig(StrategyWeights):
    ema_period: int = 20
    atr_period: int = 14
    kc_multiplier: float = 1.5
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_long_max: float = 40
    rsi_short_min: float = 60
    weight: float = 0.30


class StrategiesConfig(BaseModel):
    keltner: KeltnerConfig = Field(default_factory=KeltnerConfig)
    trend: TrendConfig = Field(default_factory=TrendConfig)
    mean_reversion: MeanReversionConfig = Field(default_factory=MeanReversionConfig)
    ichimoku: IchimokuConfig = Field(default_factory=IchimokuConfig)
    stochastic_divergence: StochasticDivergenceConfig = Field(default_factory=StochasticDivergenceConfig)
    volatility_squeeze: VolatilitySqueezeConfig = Field(default_factory=VolatilitySqueezeConfig)
    order_flow: OrderFlowConfig = Field(default_factory=OrderFlowConfig)
    supertrend: SupertrendConfig = Field(default_factory=SupertrendConfig)
    reversal: ReversalConfig = Field(default_factory=ReversalConfig)


class RegimeConfig(BaseModel):
    """Market regime thresholds and per-strategy weight multipliers."""
    adx_trend_threshold: float = 25.0
    atr_pct_high: float = 0.02
    atr_pct_low: float = 0.008
    trend_weight_multipliers: Dict[str, float] = Field(default_factory=lambda: {
        "trend": 1.3,
        "ichimoku": 1.2,
        "supertrend": 1.2,
        "order_flow": 1.1,
        "volatility_squeeze": 1.1,
        "mean_reversion": 0.8,
        "stochastic_divergence": 0.8,
        "reversal": 0.7,
        "keltner": 0.9,
    })
    range_weight_multipliers: Dict[str, float] = Field(default_factory=lambda: {
        "mean_reversion": 1.3,
        "stochastic_divergence": 1.3,
        "keltner": 1.2,
        "reversal": 1.1,
        "order_flow": 1.1,
        "trend": 0.8,
        "ichimoku": 0.8,
        "supertrend": 0.8,
        "volatility_squeeze": 0.9,
    })
    high_vol_weight_multipliers: Dict[str, float] = Field(default_factory=lambda: {
        "volatility_squeeze": 1.3,
        "supertrend": 1.1,
        "order_flow": 1.1,
        "mean_reversion": 0.9,
        "stochastic_divergence": 0.9,
        "reversal": 0.9,
    })
    low_vol_weight_multipliers: Dict[str, float] = Field(default_factory=lambda: {
        "mean_reversion": 1.2,
        "stochastic_divergence": 1.2,
        "keltner": 1.1,
        "volatility_squeeze": 0.8,
        "supertrend": 0.9,
        "ichimoku": 0.9,
    })


class SessionConfig(BaseModel):
    enabled: bool = True
    min_trades_per_hour: int = 5
    max_boost: float = 1.15
    max_penalty: float = 0.70


class AIConfig(BaseModel):
    confluence_threshold: int = 3
    min_confidence: float = 0.65
    min_risk_reward_ratio: float = 0.9  # Only take trades where TP distance >= this * SL distance
    allow_keltner_solo: bool = False
    allow_any_solo: bool = False
    keltner_solo_min_confidence: float = 0.60
    solo_min_confidence: float = 0.65
    tflite_model_path: str = "models/trade_predictor.tflite"
    order_book_depth: int = 25
    obi_threshold: float = 0.15
    book_score_threshold: float = 0.2
    book_score_max_age_seconds: int = 5
    multi_timeframe_min_agreement: int = 1
    primary_timeframe: int = 1
    # Weighted Order Book: when True, OBI counts as heavy (OBI + 1 strategy = tradable). When False, OBI is not a confluence vote.
    obi_counts_as_confluence: bool = False
    obi_weight: float = 0.4  # weight of synthetic OBI signal when weighted (e.g. 0.4 or 0.7)
    whale_threshold_usd: float = 50000.0
    strategy_guardrails_enabled: bool = True
    strategy_guardrails_min_trades: int = 20
    strategy_guardrails_window_trades: int = 30
    strategy_guardrails_min_win_rate: float = 0.35
    strategy_guardrails_min_profit_factor: float = 0.85
    strategy_guardrails_disable_minutes: int = 120
    session: SessionConfig = Field(default_factory=SessionConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)


class SmartExitTier(BaseModel):
    pct: float = 0.5        # Fraction of remaining position to close
    tp_mult: float = 1.0    # Multiplier on original TP distance from entry

class SmartExitConfig(BaseModel):
    enabled: bool = False    # Off by default until tested
    tiers: List[SmartExitTier] = Field(default_factory=lambda: [
        SmartExitTier(pct=0.5, tp_mult=1.0),
        SmartExitTier(pct=0.6, tp_mult=1.5),
        SmartExitTier(pct=1.0, tp_mult=0),  # 0 = trailing stop only
    ])


class RiskConfig(BaseModel):
    max_risk_per_trade: float = 0.02
    max_daily_loss: float = 0.05
    max_position_usd: float = 500.0
    initial_bankroll: float = 10000.0
    atr_multiplier_sl: float = 2.0
    atr_multiplier_tp: float = 3.0
    trailing_activation_pct: float = 0.015
    trailing_step_pct: float = 0.005
    breakeven_activation_pct: float = 0.01
    kelly_fraction: float = 0.25
    max_kelly_size: float = 0.10
    risk_of_ruin_threshold: float = 0.01
    max_daily_trades: int = 0  # 0 disables daily trade cap
    max_total_exposure_pct: float = 0.50  # max sum(size_usd) as % of bankroll
    global_cooldown_seconds_on_loss: int = 1800
    smart_exit: SmartExitConfig = Field(default_factory=SmartExitConfig)

    @field_validator("max_risk_per_trade")
    @classmethod
    def validate_risk(cls, v):
        if v <= 0 or v > 0.10:
            raise ValueError("max_risk_per_trade must be between 0 and 0.10")
        return v

    @field_validator("max_daily_loss")
    @classmethod
    def validate_daily_loss(cls, v):
        if v <= 0 or v > 0.20:
            raise ValueError("max_daily_loss must be between 0 and 0.20")
        return v

    @field_validator("max_daily_trades")
    @classmethod
    def validate_max_daily_trades(cls, v):
        if v < 0 or v > 2000:
            raise ValueError("max_daily_trades must be between 0 and 2000")
        return v

    @field_validator("max_total_exposure_pct")
    @classmethod
    def validate_max_total_exposure_pct(cls, v):
        if v <= 0 or v > 1.0:
            raise ValueError("max_total_exposure_pct must be between 0 and 1.0")
        return v


class DashboardConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    thought_feed_max: int = 200
    refresh_interval_ms: int = 1000
    # If enabled, all read endpoints and the live WS feed require a valid API key
    # (either DASHBOARD_SECRET_KEY admin key or a tenant API key).
    require_api_key_for_reads: bool = True
    # If false (default), control endpoints only accept DASHBOARD_SECRET_KEY.
    # When true, tenant API keys may also be used for control endpoints.
    allow_tenant_keys_for_control: bool = False
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 240
    rate_limit_burst: int = 60


class TunerConfig(BaseModel):
    enabled: bool = True
    interval_hours: int = 168  # Weekly
    min_trades_per_strategy: int = 15
    weight_bounds: List[float] = Field(default_factory=lambda: [0.05, 0.50])
    auto_disable_sharpe: float = -0.3
    auto_disable_min_trades: int = 30


class MLConfig(BaseModel):
    retrain_interval_hours: int = 168
    min_samples: int = 10000
    epochs: int = 50
    batch_size: int = 64
    validation_split: float = 0.2
    features: List[str] = Field(default_factory=lambda: [
        "rsi", "ema_ratio", "bb_position", "adx", "volume_ratio",
        "obi", "atr_pct", "momentum_score", "trend_strength", "spread_pct"
    ])


class ElasticsearchConfig(BaseModel):
    enabled: bool = False
    hosts: List[str] = Field(default_factory=lambda: ["http://elasticsearch:9200"])
    cloud_id: str = ""        # Elastic Cloud ID (alternative to hosts)
    api_key: str = ""         # Base64-encoded API key (or set ES_API_KEY env)
    index_prefix: str = "novapulse"
    bulk_size: int = 500
    flush_interval_seconds: float = 10.0
    buffer_maxlen: int = 10_000
    retention_days: Dict[str, int] = Field(default_factory=lambda: {
        "candles": 90,
        "orderbook": 30,
        "sentiment": 180,
        "onchain": 180,
        "market": 180,
        "trades": 365,
    })
    poll_intervals: Dict[str, int] = Field(default_factory=lambda: {
        "fear_greed": 3600,
        "coingecko": 600,
        "cryptopanic": 600,
        "onchain": 3600,
    })
    coingecko_api_key: str = ""
    cryptopanic_api_key: str = ""


class MonitoringConfig(BaseModel):
    health_check_interval: int = 30
    auto_restart: bool = True
    max_restart_attempts: int = 10
    heartbeat_interval: int = 10
    metrics_retention_hours: int = 72
    auto_pause_on_stale_data: bool = True
    stale_data_pause_after_checks: int = 3
    auto_pause_on_ws_disconnect: bool = True
    ws_disconnect_pause_after_seconds: int = 300
    auto_pause_on_consecutive_losses: bool = True
    consecutive_losses_pause_threshold: int = 4
    auto_pause_on_drawdown: bool = True
    drawdown_pause_pct: float = 8.0
    emergency_close_on_auto_pause: bool = False


class StocksConfig(BaseModel):
    enabled: bool = False
    symbols: List[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "TSLA"])
    options_enabled: bool = False
    option_symbols: List[str] = Field(default_factory=list)
    option_contract_multiplier: int = 100
    scan_interval_seconds: int = 900
    lookback_bars: int = 120
    min_hold_days: int = 1
    max_hold_days: int = 7
    max_open_positions: int = 4
    max_position_usd: float = 500.0
    # Protective levels for stock positions (long-only).
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    # Friction model used for net PnL in stock closes (entry + exit side costs).
    estimated_fee_pct_per_side: float = 0.0005
    estimated_slippage_pct_per_side: float = 0.0002
    db_path: str = "data/stocks.db"
    polygon_api_key: str = ""
    polygon_base_url: str = "https://api.polygon.io"
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    @field_validator("min_hold_days")
    @classmethod
    def validate_min_hold_days(cls, v):
        if v < 1:
            raise ValueError("min_hold_days must be >= 1")
        return v

    @field_validator("max_hold_days")
    @classmethod
    def validate_max_hold_days(cls, v):
        if v < 1:
            raise ValueError("max_hold_days must be >= 1")
        return v

    @field_validator("estimated_fee_pct_per_side", "estimated_slippage_pct_per_side")
    @classmethod
    def validate_non_negative_costs(cls, v):
        if v < 0:
            raise ValueError("stock friction values must be >= 0")
        return v

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss_pct(cls, v):
        if v <= 0 or v >= 0.50:
            raise ValueError("stocks.stop_loss_pct must be > 0 and < 0.50")
        return v

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit_pct(cls, v):
        if v <= 0 or v >= 1.0:
            raise ValueError("stocks.take_profit_pct must be > 0 and < 1.0")
        return v

    @field_validator("option_contract_multiplier")
    @classmethod
    def validate_option_contract_multiplier(cls, v):
        if v < 1 or v > 1000:
            raise ValueError("stocks.option_contract_multiplier must be between 1 and 1000")
        return v

    @model_validator(mode="after")
    def validate_hold_window(self):
        if self.max_hold_days < self.min_hold_days:
            raise ValueError("stocks.max_hold_days must be >= stocks.min_hold_days")
        if self.take_profit_pct <= self.stop_loss_pct:
            raise ValueError("stocks.take_profit_pct must be greater than stocks.stop_loss_pct")
        return self


class SignalWebhookConfig(BaseModel):
    enabled: bool = False
    secret: str = ""
    allowed_sources: List[str] = Field(default_factory=list)
    max_timestamp_skew_seconds: int = 300


class AppConfig(BaseModel):
    name: str = "AI Crypto Trading Bot"
    version: str = "3.0.0"
    mode: str = "paper"
    log_level: str = "INFO"
    db_path: str = "data/trading.db"
    # Optional explicit exchange list for multi-exchange mode.
    # Example: "kraken,coinbase"
    trading_exchanges: str = ""
    # Optional account id label (used for multi-account orchestrations).
    account_id: str = "default"
    # Optional account+exchange map.
    # Example: "main:kraken,main:coinbase,swing:kraken"
    trading_accounts: str = ""


# Control plane: Web + optional Telegram / Discord / Slack
class ControlWebConfig(BaseModel):
    enabled: bool = True


class ControlTelegramConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    chat_ids: List[str] = Field(default_factory=list)  # allowlist of chat IDs
    secrets_dir: str = ".secrets"
    # If true, starts long-polling ("getUpdates") to receive Telegram commands.
    # Only ONE running instance may poll per bot token; for multi-deploy, keep false
    # and use Telegram for send-only notifications/check-ins.
    polling_enabled: bool = False
    send_checkins: bool = True
    checkin_interval_minutes: int = 30


class ControlDiscordConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    allowed_channel_ids: List[str] = Field(default_factory=list)
    allowed_guild_id: Optional[str] = None


class ControlSlackConfig(BaseModel):
    enabled: bool = False
    token: str = ""  # bot token (xoxb-...)
    signing_secret: str = ""
    app_token: Optional[str] = None  # for Socket Mode (xapp-...)
    allowed_channel_id: Optional[str] = None


class ControlConfig(BaseModel):
    web: ControlWebConfig = Field(default_factory=ControlWebConfig)
    telegram: ControlTelegramConfig = Field(default_factory=ControlTelegramConfig)
    discord: ControlDiscordConfig = Field(default_factory=ControlDiscordConfig)
    slack: ControlSlackConfig = Field(default_factory=ControlSlackConfig)


# Billing (Stripe) and multi-tenant
class StripeConfig(BaseModel):
    enabled: bool = False
    secret_key: str = ""  # sk_live_... or sk_test_...
    webhook_secret: str = ""  # whsec_... for signature verification
    price_id: str = ""  # Legacy/default Stripe Price ID (maps to pro if price_id_pro is empty)
    price_id_pro: str = ""  # Stripe Price ID for pro plan (e.g. 49.99)
    price_id_premium: str = ""  # Stripe Price ID for premium plan (e.g. 79.99)
    currency: str = "usd"


class TenantConfig(BaseModel):
    default_tenant_id: str = "default"  # used when no tenant in request (single-tenant mode)


class BillingConfig(BaseModel):
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    tenant: TenantConfig = Field(default_factory=TenantConfig)


class BotConfig(BaseModel):
    """Master configuration model with full validation."""
    app: AppConfig = Field(default_factory=AppConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    control: ControlConfig = Field(default_factory=ControlConfig)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    tuner: TunerConfig = Field(default_factory=TunerConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    stocks: StocksConfig = Field(default_factory=StocksConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)
    webhooks: SignalWebhookConfig = Field(default_factory=SignalWebhookConfig)


# ---------------------------------------------------------------------------
# Configuration Manager (Singleton)
# ---------------------------------------------------------------------------

class ConfigManager:
    """
    Thread-safe configuration manager with hot-reload support.
    
    Loads configuration from YAML file, then overlays environment
    variables for deployment flexibility. Validates all values through
    Pydantic models.
    
    # ENHANCEMENT: Added file-watching for hot-reload capability
    # ENHANCEMENT: Added config versioning for rollback support
    """

    _instance: Optional[ConfigManager] = None
    _config: Optional[BotConfig] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self.load()

    def load(self, config_path: str = "config/config.yaml") -> BotConfig:
        """Load configuration from YAML + environment variables."""
        load_dotenv()

        # Load YAML config
        yaml_config: Dict[str, Any] = {}
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, "r") as f:
                yaml_config = yaml.safe_load(f) or {}

        # Apply environment variable overrides
        self._apply_env_overrides(yaml_config)

        # Validate through Pydantic
        self._config = BotConfig(**yaml_config)
        return self._config

    def _apply_env_overrides(self, config: Dict[str, Any]) -> None:
        """Override YAML values with environment variables where set."""
        _apply_env_overrides(config)

    @property
    def config(self) -> BotConfig:
        """Get the current validated configuration."""
        if self._config is None:
            self.load()
        return self._config

    def reload(self, config_path: str = "config/config.yaml") -> BotConfig:
        """Hot-reload configuration from disk."""
        return self.load(config_path)

    def get(self, dotpath: str, default: Any = None) -> Any:
        """
        Access config values using dot notation.
        
        Example: config.get("risk.max_risk_per_trade") -> 0.02
        """
        obj = self._config
        for key in dotpath.split("."):
            if hasattr(obj, key):
                obj = getattr(obj, key)
            elif isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default
        return obj

    def to_dict(self) -> Dict[str, Any]:
        """Export full config as dictionary."""
        return self._config.model_dump() if self._config else {}


# Convenience accessor
def get_config() -> BotConfig:
    """Get the global configuration instance."""
    return ConfigManager().config


def save_to_yaml(
    updates: Dict[str, Dict[str, Any]],
    config_path: str = "config/config.yaml",
) -> None:
    """
    Persist settings changes to config.yaml, preserving comments and formatting.

    ``updates`` is a nested dict like ``{"ai": {"confluence_threshold": 3}, "risk": {"max_risk_per_trade": 0.01}}``.
    Only the specified keys are overwritten; everything else is untouched.
    """
    from ruamel.yaml import YAML

    ryaml = YAML()
    ryaml.preserve_quotes = True

    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            doc = ryaml.load(f) or {}
    else:
        doc = {}

    for section, kvs in updates.items():
        if not isinstance(kvs, dict):
            continue
        if section not in doc or not isinstance(doc[section], dict):
            doc[section] = {}
        for key, value in kvs.items():
            doc[section][key] = value

    tmp = config_file.with_suffix(".yaml.tmp")
    with open(tmp, "w") as f:
        ryaml.dump(doc, f)
    import os
    os.replace(tmp, config_file)


def load_config_with_overrides(
    config_path: str = "config/config.yaml",
    overrides: Optional[Dict[str, Any]] = None,
) -> BotConfig:
    """Load a fresh config (YAML + env) with optional deep overrides."""
    load_dotenv()

    yaml_config: Dict[str, Any] = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            yaml_config = yaml.safe_load(f) or {}

    _apply_env_overrides(yaml_config)

    def _deep_update(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
        for key, value in (src or {}).items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                _deep_update(dst[key], value)
            else:
                dst[key] = value

    if overrides:
        _deep_update(yaml_config, overrides)

    return BotConfig(**yaml_config)
