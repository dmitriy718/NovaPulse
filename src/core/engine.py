"""
Bot Engine - Main orchestrator for the AI Trading Bot.

Coordinates all subsystems: market data, strategies, AI intelligence,
execution, risk management, and monitoring. Manages the main event
loop and lifecycle of the entire application.

# ENHANCEMENT: Added graceful shutdown with position preservation
# ENHANCEMENT: Added health monitoring with auto-recovery
# ENHANCEMENT: Added hot-reload for configuration changes
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ai.confluence import ConfluenceDetector, ConfluenceSignal
from src.ai.order_book import OrderBookAnalyzer
from src.ai.predictor import TFLitePredictor
from src.api.server import DashboardServer
from src.core.control_router import ControlRouter
from src.core.config import ConfigManager, get_config
from src.core.database import DatabaseManager
from src.core.error_handler import ErrorSeverity, GracefulErrorHandler
from src.core.logger import get_logger, setup_logging
from src.exchange.kraken_rest import KrakenRESTClient
from src.exchange.kraken_ws import KrakenWebSocketClient
from src.exchange.market_data import MarketDataCache
from src.execution.executor import TradeExecutor
from src.execution.risk_manager import RiskManager
from src.ml.trainer import ModelTrainer, AutoRetrainer
from src.ml.continuous_learner import ContinuousLearner
from src.ml.strategy_tuner import StrategyTuner, AutoTuner
from src.ai.session_analyzer import SessionAnalyzer
from src.strategies.base import SignalDirection, StrategySignal
from src.utils.discord_bot import DiscordBot
from src.utils.slack_bot import SlackBot
from src.utils.telegram import TelegramBot

logger = get_logger("engine")


class BotEngine:
    """
    Main orchestrator for the AI Trading Bot.
    
    Lifecycle:
    1. Initialize all subsystems
    2. Warmup market data from REST
    3. Connect WebSocket for live data
    4. Run main scan loop
    5. Manage positions on each cycle
    6. Handle shutdown gracefully
    
    # ENHANCEMENT: Added subsystem health monitoring
    # ENHANCEMENT: Added automatic data quality checks
    # ENHANCEMENT: Added event bus for inter-component communication
    """

    def __init__(self, config_override: Optional[Any] = None, enable_dashboard: bool = True):
        self.config = config_override or get_config()
        self.mode = self.config.app.mode
        self.canary_mode = bool(getattr(self.config.trading, "canary_mode", False))
        configured_pairs = list(self.config.trading.pairs or [])
        self.pairs = configured_pairs
        self.scan_interval = self.config.trading.scan_interval_seconds
        if self.canary_mode:
            canary_pairs = list(getattr(self.config.trading, "canary_pairs", []) or [])
            max_pairs = max(1, int(getattr(self.config.trading, "canary_max_pairs", 2) or 2))
            if canary_pairs:
                self.pairs = canary_pairs[:max_pairs]
            else:
                self.pairs = configured_pairs[:max_pairs]
            canary_scan_interval = max(
                1, int(getattr(self.config.trading, "canary_scan_interval_seconds", self.scan_interval) or self.scan_interval)
            )
            self.scan_interval = max(self.scan_interval, canary_scan_interval)
        self.position_check_interval = self.config.trading.position_check_interval_seconds
        self.tenant_id = self.config.billing.tenant.default_tenant_id
        self.account_id = getattr(self.config.app, "account_id", "default")
        self._enable_dashboard = enable_dashboard

        # Core components (initialized in start())
        self.db: Optional[DatabaseManager] = None
        self.rest_client: Optional[Any] = None
        self.ws_client: Optional[Any] = None
        self.market_data: Optional[MarketDataCache] = None
        self.confluence: Optional[ConfluenceDetector] = None
        self.predictor: Optional[TFLitePredictor] = None
        self.continuous_learner: Optional[ContinuousLearner] = None
        self.order_book_analyzer: Optional[OrderBookAnalyzer] = None
        self.risk_manager: Optional[RiskManager] = None
        self.executor: Optional[TradeExecutor] = None
        self.dashboard: Optional[DashboardServer] = None
        self.control_router: Optional[ControlRouter] = None
        self.telegram_bot: Optional[TelegramBot] = None
        self.discord_bot: Optional[DiscordBot] = None
        self.slack_bot: Optional[SlackBot] = None
        self.error_handler: GracefulErrorHandler = GracefulErrorHandler()

        # Elasticsearch data pipeline (initialized in initialize() if enabled)
        self.es_client = None
        self.market_data_indexer = None
        self.external_data_collector = None
        self.es_training_provider = None

        # State
        self._running = False
        self._trading_paused = False
        # If set, the bot will start in paused mode (persists across restarts via env).
        self._start_paused_requested = os.getenv("START_PAUSED", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
            "on",
        )
        self._start_time = 0.0
        self._scan_count = 0
        self._last_health_check = 0.0
        self._tasks: List[asyncio.Task] = []
        self._scan_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._pending_scan_pairs: set = set()
        self._event_price_move_pct = getattr(self.config.trading, "event_price_move_pct", 0.005)
        self.exchange_name = (self.config.exchange.name or "kraken").lower()
        self._stale_check_count = 0
        self._ws_disconnected_since: Optional[float] = None
        self._auto_pause_reason: str = ""
        # Adaptive scan interval: tracks recent event frequency
        self._recent_event_count = 0
        self._event_window_start = 0.0

    async def _auto_pause_trading(
        self,
        reason: str,
        detail: str = "",
        emergency_close: Optional[bool] = None,
    ) -> None:
        """Pause trading with audit logging and optional Telegram alert (idempotent)."""
        if self._trading_paused:
            return
        self._trading_paused = True
        self._auto_pause_reason = reason or "unknown"
        msg = f"Trading AUTO-PAUSED: {reason}"
        if detail:
            msg = f"{msg} | {detail}"
        try:
            if self.db:
                await self.db.log_thought(
                    "system",
                    msg,
                    severity="warning",
                    tenant_id=self.tenant_id,
                )
        except Exception:
            pass
        try:
            if self.telegram_bot:
                await self.telegram_bot.send_message(f"🛑 *AUTO-PAUSE*\n{msg}")
        except Exception:
            pass
        do_emergency_close = bool(
            getattr(self.config.monitoring, "emergency_close_on_auto_pause", False)
            if emergency_close is None
            else emergency_close
        )
        if do_emergency_close and self.executor:
            try:
                closed = await self.executor.close_all_positions(
                    reason=f"auto_pause:{reason}",
                    tenant_id=self.tenant_id,
                )
                if self.db:
                    await self.db.log_thought(
                        "system",
                        f"AUTO-PAUSE emergency close executed: {closed} positions closed",
                        severity="warning",
                        tenant_id=self.tenant_id,
                    )
            except Exception:
                pass

    async def _apply_circuit_breakers(self, stale_pairs: List[str]) -> None:
        """Apply simple circuit breakers (stale data, WS disconnect) to reduce blow-ups in live mode."""
        mon = getattr(self.config, "monitoring", None)
        if not mon:
            return

        # Stale data breaker
        if getattr(mon, "auto_pause_on_stale_data", True):
            if stale_pairs:
                self._stale_check_count += 1
            else:
                self._stale_check_count = 0
            threshold = int(getattr(mon, "stale_data_pause_after_checks", 3) or 3)
            if threshold < 1:
                threshold = 1
            if stale_pairs and self._stale_check_count >= threshold:
                await self._auto_pause_trading(
                    "stale_data",
                    detail=f"pairs={','.join(stale_pairs[:10])}",
                )

        # WebSocket disconnect breaker
        if getattr(mon, "auto_pause_on_ws_disconnect", True):
            ws_ok = bool(self.ws_client and getattr(self.ws_client, "is_connected", False))
            now = time.time()
            if not ws_ok:
                if self._ws_disconnected_since is None:
                    self._ws_disconnected_since = now
            else:
                self._ws_disconnected_since = None
            limit_s = int(getattr(mon, "ws_disconnect_pause_after_seconds", 300) or 300)
            if limit_s < 1:
                limit_s = 1
            if self._ws_disconnected_since is not None and (now - self._ws_disconnected_since) >= limit_s:
                await self._auto_pause_trading("ws_disconnected", detail=f">{limit_s}s")

        # Consecutive loss breaker
        if getattr(mon, "auto_pause_on_consecutive_losses", True) and self.risk_manager:
            report = self.risk_manager.get_risk_report()
            losses = int(report.get("consecutive_losses", 0) or 0)
            threshold = max(1, int(getattr(mon, "consecutive_losses_pause_threshold", 4) or 4))
            if losses >= threshold:
                await self._auto_pause_trading(
                    "consecutive_losses",
                    detail=f"{losses} consecutive losses (threshold={threshold})",
                )

        # Drawdown breaker
        if getattr(mon, "auto_pause_on_drawdown", True) and self.risk_manager:
            report = self.risk_manager.get_risk_report()
            drawdown = float(report.get("current_drawdown", 0.0) or 0.0)
            threshold_pct = max(0.1, float(getattr(mon, "drawdown_pause_pct", 8.0) or 8.0))
            if drawdown >= threshold_pct:
                await self._auto_pause_trading(
                    "drawdown_limit",
                    detail=f"drawdown={drawdown:.2f}% threshold={threshold_pct:.2f}%",
                )

    async def execute_external_signal(
        self,
        payload: Dict[str, Any],
        *,
        source: str = "webhook",
    ) -> Dict[str, Any]:
        """
        Execute a signed external signal (TradingView/custom provider).

        Expected payload fields:
        - pair (required)
        - direction: long/short/buy/sell (required)
        - confidence, strength, confluence_count (optional)
        - entry_price, stop_loss, take_profit (optional; defaults are derived)
        - strategy/provider/timestamp (optional metadata)
        """
        if not self.executor:
            return {"ok": False, "error": "executor not available"}
        if self._trading_paused:
            return {"ok": False, "error": "trading paused"}

        pair_raw = str(payload.get("pair") or "").strip().upper().replace("-", "/")
        if not pair_raw:
            return {"ok": False, "error": "pair is required"}
        pair = pair_raw

        known_pairs = {str(p).upper() for p in (self.pairs or [])}
        if known_pairs and pair not in known_pairs:
            return {"ok": False, "error": f"pair not configured: {pair}"}

        direction_raw = str(payload.get("direction") or "").strip().lower()
        if direction_raw in ("buy", "long"):
            direction = SignalDirection.LONG
            side = "buy"
        elif direction_raw in ("sell", "short"):
            direction = SignalDirection.SHORT
            side = "sell"
        else:
            return {"ok": False, "error": "direction must be long/short or buy/sell"}

        try:
            market_price = float(self.market_data.get_latest_price(pair)) if self.market_data else 0.0
        except Exception:
            market_price = 0.0
        try:
            entry_price = float(payload.get("entry_price") or market_price)
        except Exception:
            entry_price = market_price
        if entry_price <= 0:
            return {"ok": False, "error": "entry_price missing and no market price available"}

        min_conf = float(getattr(self.config.ai, "min_confidence", 0.6) or 0.6)
        confidence = payload.get("confidence", min_conf)
        strength = payload.get("strength", confidence)
        confluence_count = payload.get("confluence_count", max(2, int(self.config.ai.confluence_threshold)))

        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = min_conf
        try:
            strength = max(0.0, min(1.0, float(strength)))
        except Exception:
            strength = confidence
        try:
            confluence_count = max(1, int(confluence_count))
        except Exception:
            confluence_count = max(2, int(self.config.ai.confluence_threshold))

        # Derive defaults if SL/TP omitted.
        try:
            stop_loss = float(payload.get("stop_loss") or 0.0)
        except Exception:
            stop_loss = 0.0
        try:
            take_profit = float(payload.get("take_profit") or 0.0)
        except Exception:
            take_profit = 0.0

        try:
            stop_pct = max(0.001, float(payload.get("stop_pct", 0.01)))
        except Exception:
            stop_pct = 0.01
        try:
            rr = max(1.0, float(payload.get("risk_reward", max(1.2, self.config.ai.min_risk_reward_ratio))))
        except Exception:
            rr = max(1.2, self.config.ai.min_risk_reward_ratio)

        if stop_loss <= 0:
            stop_loss = entry_price * (1.0 - stop_pct) if side == "buy" else entry_price * (1.0 + stop_pct)
        if take_profit <= 0:
            tp_pct = stop_pct * rr
            take_profit = entry_price * (1.0 + tp_pct) if side == "buy" else entry_price * (1.0 - tp_pct)

        strategy_name = str(payload.get("strategy") or f"external_{source}").strip() or f"external_{source}"
        provider = str(payload.get("provider") or "").strip()
        timestamp = str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat())

        strategy_signal = StrategySignal(
            strategy_name=strategy_name,
            pair=pair,
            direction=direction,
            strength=float(strength),
            confidence=float(confidence),
            entry_price=float(entry_price),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            timestamp=timestamp,
            metadata={
                "external": True,
                "source": source,
                "provider": provider,
            },
        )
        confluence_signal = ConfluenceSignal(
            pair=pair,
            direction=direction,
            strength=float(strength),
            confidence=float(confidence),
            confluence_count=int(confluence_count),
            signals=[strategy_signal],
            obi=0.0,
            book_score=0.0,
            obi_agrees=False,
            is_sure_fire=False,
            entry_price=float(entry_price),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
        )
        confluence_signal.timestamp = timestamp

        trade_id = await self.executor.execute_signal(confluence_signal)
        if not trade_id:
            return {"ok": False, "error": "signal rejected by risk/execution"}

        if self.db:
            await self.db.log_thought(
                "signal",
                f"External signal executed | {pair} {direction.value.upper()} | source={source}",
                severity="info",
                metadata={
                    "source": source,
                    "provider": provider,
                    "trade_id": trade_id,
                    "signal": confluence_signal.to_dict(),
                },
                tenant_id=self.tenant_id,
            )
        return {"ok": True, "trade_id": trade_id}

    async def initialize(self) -> None:
        """Initialize all subsystems with graceful error handling.

        CRITICAL subsystems (DB, REST client): failure aborts startup.
        NON-CRITICAL subsystems (Telegram, Dashboard, ML, Billing): failure
        is logged and skipped — the bot keeps trading.
        """
        from src import __version__
        logger.info("Initializing AI Trading Bot", mode=self.mode, version=__version__)

        account_id = str(getattr(self.config.app, "account_id", self.tenant_id) or self.tenant_id).strip().lower()

        def _env_for_account(name: str, default: str = "") -> str:
            # Supports multi-account secret names like:
            # MAIN_KRAKEN_API_KEY, SWING_COINBASE_KEY_NAME, etc.
            if account_id and account_id != "default":
                prefix = "".join(ch if ch.isalnum() else "_" for ch in account_id.upper())
                scoped_key = f"{prefix}_{name}"
                scoped = os.getenv(scoped_key)
                if scoped is not None and scoped != "":
                    return scoped
            return os.getenv(name, default)

        # ---- CRITICAL: Database ----
        db_path = self.config.app.db_path
        self.db = DatabaseManager(db_path)
        await self.db.initialize()
        db_abs = str(Path(db_path).resolve())
        logger.info(
            "Database initialized",
            path=db_path,
            path_abs=db_abs,
            exists=Path(db_abs).exists(),
            wal_exists=Path(f"{db_abs}-wal").exists(),
            shm_exists=Path(f"{db_abs}-shm").exists(),
            exchange=self.exchange_name,
            account_id=self.tenant_id,
        )
        logger.info(
            "Persistence contract",
            canonical_ledger="sqlite",
            elasticsearch_role="analytics_mirror",
            sqlite_path=db_abs,
            exchange=self.exchange_name,
            account_id=self.tenant_id,
        )

        # Wire up error handler's DB logging now that DB is ready.
        self.error_handler.set_db_log_fn(
            lambda cat, msg, severity="info": self.db.log_thought(
                cat, msg, severity=severity, tenant_id=self.tenant_id,
            )
        )

        # ---- CRITICAL: REST + WebSocket Clients ----
        if self.exchange_name == "coinbase":
            from src.exchange.coinbase_rest import CoinbaseAuthConfig, CoinbaseRESTClient
            from src.exchange.coinbase_ws import CoinbaseWebSocketClient

            is_sandbox = _env_for_account("COINBASE_SANDBOX", "false").lower() in ("true", "1", "yes")
            rest_url = self.config.exchange.rest_url
            ws_url = self.config.exchange.ws_url
            if "kraken" in rest_url:
                rest_url = CoinbaseRESTClient.DEFAULT_SANDBOX_URL if is_sandbox else CoinbaseRESTClient.DEFAULT_REST_URL
            if "kraken" in ws_url:
                ws_url = CoinbaseWebSocketClient.DEFAULT_WS_URL
            market_data_url = _env_for_account("COINBASE_MARKET_DATA_URL", "").strip() or None
            if is_sandbox and not market_data_url:
                logger.warning(
                    "Coinbase sandbox has limited market data endpoints",
                    hint="Set COINBASE_MARKET_DATA_URL to production if needed",
                )

            key_name = _env_for_account("COINBASE_KEY_NAME", "").strip()
            if not key_name:
                org_id = _env_for_account("COINBASE_ORG_ID", "").strip()
                key_id = _env_for_account("COINBASE_KEY_ID", "").strip()
                if org_id and key_id:
                    key_name = f"organizations/{org_id}/apiKeys/{key_id}"

            private_key_pem = ""
            inline_private_key = _env_for_account("COINBASE_PRIVATE_KEY", "").strip()
            if inline_private_key:
                private_key_pem = inline_private_key
            else:
                key_path = _env_for_account("COINBASE_PRIVATE_KEY_PATH", "").strip()
                if key_path and os.path.exists(key_path):
                    with open(key_path, "r") as f:
                        private_key_pem = f.read()
            if "\\n" in private_key_pem and "\n" not in private_key_pem:
                private_key_pem = private_key_pem.replace("\\n", "\n")

            auth_cfg = None
            if key_name and private_key_pem:
                auth_cfg = CoinbaseAuthConfig(key_name=key_name, private_key_pem=private_key_pem)
            else:
                logger.warning(
                    "Coinbase auth not configured",
                    has_key_name=bool(key_name),
                    has_private_key=bool(private_key_pem),
                )

            self.rest_client = CoinbaseRESTClient(
                rest_url=rest_url,
                market_data_url=market_data_url,
                rate_limit=self.config.exchange.rate_limit_per_second,
                max_retries=self.config.exchange.max_retries,
                timeout=self.config.exchange.timeout,
                sandbox=is_sandbox,
                auth_config=auth_cfg,
            )
            await self.rest_client.initialize()
            logger.info(
                "REST client initialized",
                exchange="coinbase",
                account=account_id,
                sandbox=is_sandbox,
                mode=self.mode,
                has_key=bool(auth_cfg),
            )

            self.ws_client = CoinbaseWebSocketClient(url=ws_url)
        else:
            api_key = _env_for_account("KRAKEN_API_KEY", "")
            api_secret = _env_for_account("KRAKEN_API_SECRET", "")
            is_sandbox = _env_for_account("KRAKEN_SANDBOX", "false").lower() in ("true", "1", "yes")

            self.rest_client = KrakenRESTClient(
                api_key=api_key,
                api_secret=api_secret,
                rate_limit=self.config.exchange.rate_limit_per_second,
                max_retries=self.config.exchange.max_retries,
            )
            await self.rest_client.initialize()
            logger.info(
                "REST client initialized",
                exchange="kraken",
                account=account_id,
                sandbox=is_sandbox,
                mode=self.mode,
                has_key=bool(api_key),
            )

            self.ws_client = KrakenWebSocketClient(
                url=self.config.exchange.ws_url,
            )

        # Market Data Cache
        self.market_data = MarketDataCache(
            max_bars=self.config.trading.warmup_bars,
        )

        # ---- NON-CRITICAL: Session Analyzer ----
        self.session_analyzer: Optional[SessionAnalyzer] = None
        try:
            session_cfg = getattr(self.config.ai, "session", None)
            if session_cfg and getattr(session_cfg, "enabled", True):
                self.session_analyzer = SessionAnalyzer(
                    db=self.db,
                    min_trades_per_hour=getattr(session_cfg, "min_trades_per_hour", 5),
                    max_boost=getattr(session_cfg, "max_boost", 1.15),
                    max_penalty=getattr(session_cfg, "max_penalty", 0.70),
                    tenant_id=self.tenant_id,
                )
                logger.info("Session analyzer initialized")
        except Exception as e:
            await self.error_handler.handle(e, component="session_analyzer", context="init")

        # ---- NON-CRITICAL: AI Components ----
        try:
            self.confluence = ConfluenceDetector(
                market_data=self.market_data,
                confluence_threshold=self.config.ai.confluence_threshold,
                obi_threshold=self.config.ai.obi_threshold,
                book_score_threshold=getattr(self.config.ai, "book_score_threshold", 0.2),
                book_score_max_age_seconds=getattr(self.config.ai, "book_score_max_age_seconds", 5),
                min_confidence=self.config.ai.min_confidence,
                obi_counts_as_confluence=getattr(
                    self.config.ai, "obi_counts_as_confluence", False
                ),
                obi_weight=getattr(self.config.ai, "obi_weight", 0.4),
                round_trip_fee_pct=self.config.exchange.taker_fee * 2,
                use_closed_candles_only=getattr(self.config.trading, "use_closed_candles_only", False),
                regime_config=getattr(self.config.ai, "regime", None),
                timeframes=getattr(self.config.trading, "timeframes", [1]),
                multi_timeframe_min_agreement=getattr(self.config.ai, "multi_timeframe_min_agreement", 1),
                primary_timeframe=getattr(self.config.ai, "primary_timeframe", 1),
                session_analyzer=self.session_analyzer,
                strategy_guardrails_enabled=getattr(self.config.ai, "strategy_guardrails_enabled", True),
                strategy_guardrails_min_trades=getattr(self.config.ai, "strategy_guardrails_min_trades", 20),
                strategy_guardrails_window_trades=getattr(self.config.ai, "strategy_guardrails_window_trades", 30),
                strategy_guardrails_min_win_rate=getattr(self.config.ai, "strategy_guardrails_min_win_rate", 0.35),
                strategy_guardrails_min_profit_factor=getattr(
                    self.config.ai, "strategy_guardrails_min_profit_factor", 0.85
                ),
                strategy_guardrails_disable_minutes=getattr(
                    self.config.ai, "strategy_guardrails_disable_minutes", 120
                ),
            )
            self.confluence.configure_strategies(
                self.config.strategies.model_dump(),
                single_strategy_mode=getattr(
                    self.config.trading, "single_strategy_mode", None
                ),
            )
        except Exception as e:
            await self.error_handler.handle(e, component="confluence", context="init")

        try:
            self.predictor = TFLitePredictor(
                model_path=self.config.ai.tflite_model_path,
                feature_names=self.config.ml.features,
            )
            self.predictor.load_model()
        except Exception as e:
            await self.error_handler.handle(e, component="predictor", context="init")

        enabled = (os.getenv("CONTINUOUS_LEARNING_ENABLED", "true") or "").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        if enabled:
            try:
                self.continuous_learner = ContinuousLearner(
                    model_path=str(Path("models") / "continuous_sgd.joblib"),
                    feature_names=self.config.ml.features,
                )
                logger.info("Continuous learner enabled", model_path=str(Path("models") / "continuous_sgd.joblib"))
            except Exception as e:
                await self.error_handler.handle(e, component="continuous_learner", context="init")
                self.continuous_learner = None

        try:
            self.order_book_analyzer = OrderBookAnalyzer(
                whale_threshold_usd=self.config.ai.whale_threshold_usd,
                depth=self.config.ai.order_book_depth,
            )
        except Exception as e:
            await self.error_handler.handle(e, component="order_book_analyzer", context="init")

        # Risk Manager
        initial_bankroll = float(self.config.risk.initial_bankroll)
        max_risk_per_trade = float(self.config.risk.max_risk_per_trade)
        max_position_usd = float(self.config.risk.max_position_usd)
        max_concurrent_positions = int(self.config.trading.max_concurrent_positions)
        cooldown_seconds = 60 if self.mode == "paper" else int(self.config.trading.cooldown_seconds)
        if self.canary_mode:
            max_risk_per_trade = min(
                max_risk_per_trade,
                float(getattr(self.config.trading, "canary_max_risk_per_trade", max_risk_per_trade)),
            )
            max_position_usd = min(
                max_position_usd,
                float(getattr(self.config.trading, "canary_max_position_usd", max_position_usd)),
            )
            max_concurrent_positions = 1
            cooldown_seconds = max(cooldown_seconds, int(self.config.trading.cooldown_seconds))

        self.risk_manager = RiskManager(
            initial_bankroll=initial_bankroll,
            max_risk_per_trade=max_risk_per_trade,
            max_daily_loss=self.config.risk.max_daily_loss,
            max_position_usd=max_position_usd,
            kelly_fraction=self.config.risk.kelly_fraction,
            max_kelly_size=self.config.risk.max_kelly_size,
            risk_of_ruin_threshold=self.config.risk.risk_of_ruin_threshold,
            max_daily_trades=getattr(self.config.risk, "max_daily_trades", 0),
            max_total_exposure_pct=getattr(self.config.risk, "max_total_exposure_pct", 0.50),
            atr_multiplier_sl=self.config.risk.atr_multiplier_sl,
            atr_multiplier_tp=self.config.risk.atr_multiplier_tp,
            trailing_activation_pct=self.config.risk.trailing_activation_pct,
            trailing_step_pct=self.config.risk.trailing_step_pct,
            breakeven_activation_pct=self.config.risk.breakeven_activation_pct,
            cooldown_seconds=cooldown_seconds,
            max_concurrent_positions=max_concurrent_positions,
            strategy_cooldowns=self.config.trading.strategy_cooldowns_seconds,
            global_cooldown_seconds_on_loss=self.config.risk.global_cooldown_seconds_on_loss,
            min_risk_reward_ratio=getattr(self.config.ai, "min_risk_reward_ratio", 1.2),
        )
        # Sync bankroll with historical P/L from DB so restarts don't
        # cause a mismatch between the displayed total P/L (from DB) and
        # the bankroll (which was reset to initial_bankroll).
        try:
            hist = await self.db.get_performance_stats(tenant_id=self.tenant_id)
            historical_pnl = float(hist.get("total_pnl", 0.0) or 0.0)
            if historical_pnl != 0.0:
                self.risk_manager.current_bankroll = initial_bankroll + historical_pnl
                self.risk_manager._peak_bankroll = max(
                    self.risk_manager._peak_bankroll,
                    self.risk_manager.current_bankroll,
                )
                logger.info(
                    "Bankroll synced with historical P/L",
                    initial=initial_bankroll,
                    historical_pnl=round(historical_pnl, 2),
                    adjusted_bankroll=round(self.risk_manager.current_bankroll, 2),
                )
        except Exception as e:
            logger.warning("Could not sync bankroll with DB history", error=repr(e))

        if self.confluence:
            self.confluence.set_cooldown_checker(
                self.risk_manager.is_strategy_on_cooldown
            )

        # Trade Executor
        self.executor = TradeExecutor(
            rest_client=self.rest_client,
            market_data=self.market_data,
            risk_manager=self.risk_manager,
            db=self.db,
            mode=self.mode,
            maker_fee=self.config.exchange.maker_fee,
            taker_fee=self.config.exchange.taker_fee,
            post_only=self.config.exchange.post_only,
            tenant_id=self.tenant_id,
            limit_chase_attempts=self.config.exchange.limit_chase_attempts,
            limit_chase_delay_seconds=self.config.exchange.limit_chase_delay_seconds,
            limit_fallback_to_market=self.config.exchange.limit_fallback_to_market,
            es_client=self.es_client,
            strategy_result_cb=self.confluence.record_trade_result if self.confluence else None,
            max_trades_per_hour=getattr(self.config.trading, "max_trades_per_hour", 0),
        )
        if self.continuous_learner:
            self.executor.set_continuous_learner(self.continuous_learner)

        # ---- NON-CRITICAL: ML Training Components ----
        try:
            self.ml_trainer = ModelTrainer(
                db=self.db,
                min_samples=self.config.ml.min_samples,
                epochs=self.config.ml.epochs,
                batch_size=self.config.ml.batch_size,
                feature_names=self.config.ml.features,
                tenant_id=self.tenant_id,
            )
            self.retrainer = AutoRetrainer(
                trainer=self.ml_trainer,
                interval_hours=self.config.ml.retrain_interval_hours,
            )
        except Exception as e:
            await self.error_handler.handle(e, component="ml", context="init")
            # Provide a no-op retrainer so background loops don't crash.
            self.retrainer = type("_NoOp", (), {"run": staticmethod(lambda: asyncio.sleep(3600))})()

        # ---- NON-CRITICAL: Auto Strategy Tuner ----
        self.auto_tuner = None
        try:
            tuner_cfg = getattr(self.config, "tuner", None)
            if tuner_cfg and getattr(tuner_cfg, "enabled", True):
                weight_bounds = tuple(getattr(tuner_cfg, "weight_bounds", [0.05, 0.50]))
                strategy_tuner = StrategyTuner(
                    db=self.db,
                    config_path="config/config.yaml",
                    min_trades_per_strategy=getattr(tuner_cfg, "min_trades_per_strategy", 15),
                    weight_bounds=weight_bounds,
                    auto_disable_sharpe=getattr(tuner_cfg, "auto_disable_sharpe", -0.3),
                    auto_disable_min_trades=getattr(tuner_cfg, "auto_disable_min_trades", 30),
                    tenant_id=self.tenant_id,
                )
                self.auto_tuner = AutoTuner(
                    tuner=strategy_tuner,
                    interval_hours=getattr(tuner_cfg, "interval_hours", 168),
                )
                logger.info("Auto strategy tuner initialized", interval_hours=tuner_cfg.interval_hours)
        except Exception as e:
            await self.error_handler.handle(e, component="strategy_tuner", context="init")

        # Restore open positions state
        await self.executor.reinitialize_positions()

        # Control Router (always available)
        self.control_router = ControlRouter(self)

        # ---- NON-CRITICAL: Dashboard ----
        if self._enable_dashboard:
            try:
                self.dashboard = DashboardServer()
                self.dashboard.set_bot_engine(self)
                self.dashboard.set_control_router(self.control_router)
            except Exception as e:
                await self.error_handler.handle(e, component="dashboard", context="init")

        # ---- NON-CRITICAL: Telegram ----
        notification_targets = []
        try:
            tcfg = getattr(self.config, "control", None)
            tcfg = getattr(tcfg, "telegram", None) if tcfg else None
            if tcfg and getattr(tcfg, "enabled", False):
                chat_ids = tcfg.chat_ids or None
                self.telegram_bot = TelegramBot(
                    token=tcfg.token,
                    chat_ids=chat_ids,
                    secrets_dir=getattr(tcfg, "secrets_dir", ".secrets") or ".secrets",
                    polling_enabled=bool(getattr(tcfg, "polling_enabled", False)),
                )
                self.telegram_bot.set_bot_engine(self)
                self.telegram_bot.set_control_router(self.control_router)
                await self.telegram_bot.initialize()
                notification_targets.append(self.telegram_bot.send_message)
                # Attach Telegram alerts to root logger so ALL ERROR+ logs
                # are automatically forwarded to Telegram.
                from src.core.logger import attach_telegram_alerts
                attach_telegram_alerts(self.telegram_bot, min_interval=10.0)
        except Exception as e:
            await self.error_handler.handle(e, component="telegram", context="init")

        # ---- NON-CRITICAL: Discord ----
        try:
            dcfg = getattr(self.config, "control", None)
            dcfg = getattr(dcfg, "discord", None) if dcfg else None
            if dcfg and getattr(dcfg, "enabled", False):
                self.discord_bot = DiscordBot(
                    token=dcfg.token,
                    allowed_channel_ids=dcfg.allowed_channel_ids,
                    allowed_guild_id=dcfg.allowed_guild_id,
                )
                self.discord_bot.set_control_router(self.control_router)
                ok = await self.discord_bot.initialize()
                if ok:
                    notification_targets.append(self.discord_bot.send_message)
        except Exception as e:
            await self.error_handler.handle(e, component="discord", context="init")

        # ---- NON-CRITICAL: Slack ----
        try:
            scfg = getattr(self.config, "control", None)
            scfg = getattr(scfg, "slack", None) if scfg else None
            if scfg and getattr(scfg, "enabled", False):
                self.slack_bot = SlackBot(
                    token=scfg.token,
                    signing_secret=scfg.signing_secret,
                    app_token=scfg.app_token,
                    allowed_channel_id=scfg.allowed_channel_id,
                )
                self.slack_bot.set_control_router(self.control_router)
                ok = await self.slack_bot.initialize()
                if ok:
                    notification_targets.append(self.slack_bot.send_message)
        except Exception as e:
            await self.error_handler.handle(e, component="slack", context="init")

        if notification_targets:
            async def _notify_all(msg: str) -> None:
                for notify in notification_targets:
                    try:
                        await notify(msg)
                    except Exception:
                        continue

            self.error_handler.set_notify_fn(_notify_all)

        # ---- NON-CRITICAL: Billing (Stripe) ----
        try:
            billing = getattr(self.config, "billing", None)
            if billing and getattr(billing.stripe, "enabled", False) and self.dashboard:
                from src.billing.stripe_service import StripeService
                stripe_cfg = billing.stripe
                stripe_svc = StripeService(
                    secret_key=stripe_cfg.secret_key,
                    webhook_secret=stripe_cfg.webhook_secret,
                    price_id=stripe_cfg.price_id,
                    currency=stripe_cfg.currency,
                    db=self.db,
                )
                self.dashboard.set_stripe_service(stripe_svc)
        except Exception as e:
            await self.error_handler.handle(e, component="billing", context="init")

        # ---- NON-CRITICAL: Elasticsearch Data Pipeline ----
        try:
            es_cfg = getattr(self.config, "elasticsearch", None)
            if es_cfg and getattr(es_cfg, "enabled", False):
                from src.data.es_client import ESClient
                from src.data.ingestion import ExternalDataCollector, MarketDataIndexer
                from src.data.training_data import ESTrainingDataProvider

                self.es_client = ESClient(
                    hosts=es_cfg.hosts,
                    index_prefix=es_cfg.index_prefix,
                    bulk_size=es_cfg.bulk_size,
                    flush_interval=es_cfg.flush_interval_seconds,
                    buffer_maxlen=es_cfg.buffer_maxlen,
                    retention_days=es_cfg.retention_days,
                    api_key=es_cfg.api_key,
                    cloud_id=es_cfg.cloud_id,
                )
                connected = await self.es_client.connect()
                if connected:
                    es_target = "cloud" if es_cfg.cloud_id else "hosts"
                    self.market_data_indexer = MarketDataIndexer(
                        es=self.es_client,
                        market_data=self.market_data,
                    )
                    polls = es_cfg.poll_intervals or {}
                    self.external_data_collector = ExternalDataCollector(
                        es=self.es_client,
                        pairs=self.pairs,
                        coingecko_api_key=es_cfg.coingecko_api_key,
                        cryptopanic_api_key=es_cfg.cryptopanic_api_key,
                        fear_greed_interval=polls.get("fear_greed", 3600),
                        coingecko_interval=polls.get("coingecko", 600),
                        cryptopanic_interval=polls.get("cryptopanic", 600),
                        onchain_interval=polls.get("onchain", 3600),
                    )
                    self.es_training_provider = ESTrainingDataProvider(es=self.es_client)
                    if self.executor:
                        self.executor.set_es_client(self.es_client)
                    # Wire into ML trainer
                    if hasattr(self, "ml_trainer") and self.ml_trainer:
                        self.ml_trainer.set_es_provider(self.es_training_provider)
                    logger.info(
                        "Elasticsearch data pipeline initialized",
                        target=es_target,
                        hosts=list(es_cfg.hosts or []),
                        cloud_id_set=bool(es_cfg.cloud_id),
                        index_prefix=es_cfg.index_prefix,
                        role="analytics_mirror_only",
                    )
                else:
                    logger.warning("Elasticsearch connection failed, data pipeline disabled")
                    self.es_client = None
        except Exception as e:
            await self.error_handler.handle(e, component="elasticsearch", context="init")
            self.es_client = None

        await self.db.log_thought(
            "system",
            f"Bot initialized in {self.mode.upper()} mode | "
            f"Tracking {len(self.pairs)} pairs | "
            f"Bankroll: ${initial_bankroll:,.2f}",
            severity="info",
            tenant_id=self.tenant_id,
        )
        if self.canary_mode:
            await self.db.log_thought(
                "system",
                f"Canary mode ACTIVE | pairs={','.join(self.pairs)} | "
                f"risk_cap={max_risk_per_trade:.4f} | position_cap=${max_position_usd:.2f}",
                severity="warning",
                tenant_id=self.tenant_id,
            )

        if self._start_paused_requested:
            self._trading_paused = True
            await self.db.log_thought(
                "system",
                "Trading START_PAUSED via START_PAUSED env var",
                severity="warning",
                tenant_id=self.tenant_id,
            )

        logger.info(
            "All subsystems initialized",
            pairs=len(self.pairs),
            mode=self.mode,
            bankroll=initial_bankroll,
        )

    async def warmup(self) -> None:
        """
        Load historical data for all pairs.
        
        # ENHANCEMENT: Added parallel warmup for speed
        # ENHANCEMENT: Added progress tracking
        """
        logger.info("Starting historical data warmup", pairs=len(self.pairs))

        await self.db.log_thought(
            "system",
            f"Warming up {len(self.pairs)} pairs with {self.config.trading.warmup_bars} bars...",
            severity="info",
            tenant_id=self.tenant_id,
        )

        tasks = [self._warmup_pair(pair) for pair in self.pairs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(
            "Warmup complete",
            success=success,
            total=len(self.pairs),
        )

        await self.db.log_thought(
            "system",
            f"Warmup complete: {success}/{len(self.pairs)} pairs loaded",
            severity="info",
            tenant_id=self.tenant_id,
        )

    async def _warmup_pair(self, pair: str) -> int:
        """Warmup a single pair with historical data.

        Kraken returns max 720 bars per OHLC request.  When warmup_bars
        exceeds 720 we make two calls to cover the full range.
        """
        try:
            target_bars = self.config.trading.warmup_bars
            if target_bars > 720:
                # First call: fetch older chunk via `since`
                since_ts = int(time.time()) - target_bars * 60
                older = await self.rest_client.get_ohlc(pair, interval=1, since=since_ts)
                # Second call: fetch latest chunk (may overlap)
                recent = await self.rest_client.get_ohlc(pair, interval=1, since=None)

                # Merge by timestamp (both are sorted ascending)
                seen = set()
                merged: list = []
                for bar in (older or []) + (recent or []):
                    ts = bar[0] if bar else None
                    if ts is not None and ts not in seen:
                        seen.add(ts)
                        merged.append(bar)
                merged.sort(key=lambda b: b[0])
                ohlc = merged
            else:
                ohlc = await self.rest_client.get_ohlc(pair, interval=1, since=None)

            if ohlc:
                bars = await self.market_data.warmup(pair, ohlc)
                logger.debug("Pair warmup complete", pair=pair, bars=bars)
                return bars
            return 0
        except Exception as e:
            logger.error("Pair warmup failed", pair=pair, error=str(e))
            raise

    # S14 FIX: Removed dead start() method. main.py manages lifecycle directly.

    async def stop(self) -> None:
        """Gracefully stop the bot engine."""
        logger.info("Stopping bot engine...")
        self._running = False

        # Cancel all tasks and WAIT for them to finish with a timeout
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Some tasks did not finish within 15s shutdown timeout",
                    pending=[t.get_name() for t in self._tasks if not t.done()],
                )

        # Now safe to close resources
        if self.es_client:
            try:
                await self.es_client.close()
            except Exception:
                pass
        if self.ws_client:
            await self.ws_client.disconnect()
        if self.rest_client:
            await self.rest_client.close()
        if self.db:
            try:
                await self.db.log_thought(
                    "system", "Bot engine STOPPED", severity="warning",
                    tenant_id=self.tenant_id,
                )
            except Exception:
                pass
            await self.db.close()
        if self.telegram_bot:
            try:
                await self.telegram_bot.stop()
            except Exception:
                pass
        if self.discord_bot:
            try:
                await self.discord_bot.stop()
            except Exception:
                pass
        if self.slack_bot:
            try:
                await self.slack_bot.stop()
            except Exception:
                pass

        logger.info("Bot engine stopped")

    # ------------------------------------------------------------------
    # Main Loops
    # ------------------------------------------------------------------

    async def _main_scan_loop(self) -> None:
        """
        Main trading scan loop.
        
        Cycles:
        1. Scan all pairs for signals
        2. Evaluate confluence
        3. Execute qualifying signals
        """
        logger.info("Main scan loop started", interval=self.scan_interval)

        while self._running:
            try:
                cycle_start = time.time()
                self._scan_count += 1

                # Step 1: Skip signal processing if paused
                if self._trading_paused:
                    await asyncio.sleep(self.scan_interval)
                    continue

                # Step 2: Refresh session analyzer (hourly, non-blocking)
                if self.session_analyzer:
                    try:
                        await self.session_analyzer.maybe_refresh()
                    except Exception:
                        pass  # Non-critical

                # Step 3: Run confluence analysis on event-driven pairs
                pairs_to_scan, from_event = await self._collect_scan_pairs()
                if not self.confluence:
                    logger.warning("Confluence detector not initialized, skipping scan")
                    await asyncio.sleep(self.scan_interval)
                    continue
                confluence_signals = await self.confluence.scan_all_pairs(
                    pairs_to_scan
                )

                # Step 3: Process signals through AI predictor
                # Use config threshold (default 3) for higher-quality, fewer trades; allow 2+ with strong confidence
                min_confluence = getattr(self.config.ai, "confluence_threshold", 3)
                min_confluence = max(2, min_confluence)  # At least 2 strategies must agree
                exec_confidence = getattr(self.config.ai, "min_confidence", 0.50)
                exec_confidence = max(0.45, min(exec_confidence, 0.75))  # Keep within sane bounds
                if self.canary_mode:
                    min_confluence = max(
                        min_confluence,
                        int(getattr(self.config.trading, "canary_min_confluence", 3)),
                    )
                    exec_confidence = max(
                        exec_confidence,
                        float(getattr(self.config.trading, "canary_min_confidence", 0.68)),
                    )
                allow_keltner_solo = getattr(self.config.ai, "allow_keltner_solo", False)
                allow_any_solo = getattr(self.config.ai, "allow_any_solo", False)
                if self.canary_mode:
                    allow_keltner_solo = False
                    allow_any_solo = False
                keltner_solo_min = getattr(self.config.ai, "keltner_solo_min_confidence", 0.60)
                solo_min = getattr(self.config.ai, "solo_min_confidence", 0.65)

                for signal in confluence_signals:
                    if signal.direction == SignalDirection.NEUTRAL:
                        continue

                    # Distinguish real strategy votes from synthetic order-book vote.
                    directional_real_votes = sum(
                        1
                        for s in signal.signals
                        if s.direction == signal.direction and s.strategy_name != "order_book"
                    )

                    # AI verification for all non-neutral signals
                    prediction_features = self._build_prediction_features(signal)
                    # Persist features for post-trade labeling/training.
                    # This also allows the executor to record what the model saw at entry.
                    try:
                        setattr(signal, "prediction_features", prediction_features)
                    except Exception:
                        pass
                    base_ai = self.predictor.predict(prediction_features) if self.predictor else 0.5
                    online_ai = None
                    if self.continuous_learner:
                        try:
                            online_ai = await self.continuous_learner.predict_proba(prediction_features)
                        except Exception:
                            online_ai = None

                    # Prefer online model when available; otherwise use base predictor.
                    if online_ai is not None:
                        if self.predictor and self.predictor.is_model_loaded:
                            ai_confidence = 0.6 * base_ai + 0.4 * online_ai
                        else:
                            ai_confidence = online_ai
                    else:
                        ai_confidence = base_ai

                    # Blend: for solo signals let strategy dominate so we still collect data.
                    pre_blend = signal.confidence
                    if directional_real_votes <= 1:
                        signal.confidence = 0.7 * pre_blend + 0.3 * ai_confidence
                    else:
                        blended = (pre_blend + ai_confidence) / 2
                        # Prevent AI from fully vetoing strong multi-strategy consensus.
                        signal.confidence = max(blended, pre_blend * 0.85)

                    try:
                        setattr(signal, "online_ai_confidence", online_ai)
                    except Exception:
                        pass

                    # Log ALL analysis thoughts so dashboard shows activity
                    await self.db.log_thought(
                        "analysis",
                        f"🔍 {signal.pair} | {signal.direction.value.upper()} | "
                        f"Confluence: {signal.confluence_count}/"
                        f"{len(self.confluence.strategies) + (1 if self.confluence.obi_counts_as_confluence else 0)} | "
                        f"Strength: {signal.strength:.2f} | "
                        f"AI Conf: {ai_confidence:.2f} | "
                        f"OBI: {signal.obi:+.3f} | "
                        f"BOOK: {getattr(signal, 'book_score', 0.0):+.3f} "
                        f"{'✨ SURE FIRE' if signal.is_sure_fire else ''}",
                        severity="info",
                        metadata=signal.to_dict(),
                        tenant_id=self.tenant_id,
                    )

                    # Determine if we should trade this signal:
                    # - Normal: 2+ strategies agreeing (confluence >= 2)
                    # - Solo (optional): Keltner or any strategy with strict confidence gates
                    has_keltner = any(
                        s.strategy_name == "keltner" and s.is_actionable
                        for s in signal.signals
                        if s.direction == signal.direction
                    )
                    keltner_solo_ok = (
                        allow_keltner_solo
                        and has_keltner
                        and directional_real_votes == 1
                        and signal.confidence >= keltner_solo_min
                    )
                    any_solo_ok = (
                        allow_any_solo
                        and directional_real_votes == 1
                        and signal.confidence >= solo_min
                    )

                    if directional_real_votes < min_confluence and not keltner_solo_ok and not any_solo_ok:
                        continue

                    # Skip trades with poor risk/reward (TP distance should be at least min_rr * SL distance)
                    sl_dist = abs(signal.entry_price - (signal.stop_loss or 0))
                    tp_dist = abs((signal.take_profit or 0) - signal.entry_price) if signal.take_profit else 0
                    min_rr = getattr(self.config.ai, "min_risk_reward_ratio", 0.9)
                    if sl_dist > 0 and tp_dist > 0 and (tp_dist / sl_dist) < min_rr:
                        continue

                    # Skip if spread too wide
                    max_spread = getattr(self.config.trading, "max_spread_pct", 0.0) or 0.0
                    if max_spread > 0:
                        book = self.market_data.get_order_book(signal.pair) if self.market_data else {}
                        book_age = time.time() - float(book.get("updated_at", 0) or 0)
                        max_book_age = max(
                            1.0,
                            float(getattr(self.config.ai, "book_score_max_age_seconds", 5) or 5),
                        )
                        spread = self.market_data.get_spread(signal.pair)
                        if spread <= 0 or book_age > max_book_age or spread > max_spread:
                            continue

                    # Execute if meets threshold
                    if signal.confidence >= exec_confidence:
                        trade_id = await self.executor.execute_signal(signal)
                        if trade_id:
                            logger.info(
                                "Signal executed",
                                trade_id=trade_id,
                                pair=signal.pair,
                                direction=signal.direction.value,
                            )

                # Log cycle metrics - every scan for visibility
                cycle_time = (time.time() - cycle_start) * 1000
                active_count = sum(1 for s in confluence_signals if s.direction != SignalDirection.NEUTRAL)
                if self._scan_count % 10 == 0 or active_count > 0:
                    await self.db.insert_metric(
                        "scan_cycle_ms",
                        cycle_time,
                        tenant_id=self.tenant_id,
                    )
                    await self.db.log_thought(
                        "system",
                        f"Scan #{self._scan_count} | {cycle_time:.0f}ms | "
                        f"Signals: {active_count}/{len(pairs_to_scan)} pairs",
                        severity="debug",
                        tenant_id=self.tenant_id,
                    )
                # Next cycle is gated by _collect_scan_pairs (event-driven or timeout)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Scan loop error",
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
                try:
                    await self.db.log_thought(
                        "system",
                        f"Scan loop error: {type(e).__name__} {e}",
                        severity="error",
                        tenant_id=self.tenant_id,
                    )
                except Exception:
                    pass
                await asyncio.sleep(5)

    async def _position_management_loop(self) -> None:
        """Manage open positions (stops/trailing) on a short, fixed interval."""
        interval = max(1, int(self.position_check_interval))
        logger.info("Position management loop started", interval=interval)
        while self._running:
            try:
                if self.executor:
                    await self.executor.manage_open_positions()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Position management loop error",
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
                await asyncio.sleep(1)

    async def _ws_data_loop(self) -> None:
        """WebSocket data streaming loop."""
        try:
            # Register callbacks
            self.ws_client.on_ticker(self._handle_ticker)
            self.ws_client.on_ohlc(self._handle_ohlc)
            self.ws_client.on_book(self._handle_book)
            self.ws_client.on_trade(self._handle_trade)

            # Subscribe to channels
            await self.ws_client.subscribe_ticker(self.pairs)
            await self.ws_client.subscribe_ohlc(self.pairs, interval=1)
            await self.ws_client.subscribe_book(
                self.pairs, depth=self.config.ai.order_book_depth
            )

            # Connect (blocking - handles reconnection internally)
            await self.ws_client.connect()

        except asyncio.CancelledError:
            await self.ws_client.disconnect()
        except Exception as e:
            logger.error(
                "WebSocket loop error",
                error=repr(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )

    async def _rest_candle_poll_loop(self) -> None:
        """Poll REST candles (Coinbase) to maintain 1m base timeframe."""
        interval = max(30, int(getattr(self.config.trading, "candle_poll_seconds", 60)))
        logger.info("REST candle poll loop started", interval=interval)
        while self._running:
            try:
                for pair in self.pairs:
                    ohlc = await self.rest_client.get_ohlc(pair, interval=1, limit=5)
                    for bar in ohlc[-5:]:
                        is_new_bar = await self.market_data.update_bar(pair, {
                            "time": float(bar[0]),
                            "open": float(bar[1]),
                            "high": float(bar[2]),
                            "low": float(bar[3]),
                            "close": float(bar[4]),
                            "vwap": float(bar[5]) if len(bar) > 5 else 0,
                            "volume": float(bar[6]) if len(bar) > 6 else 0,
                            "count": float(bar[7]) if len(bar) > 7 else 0,
                        })
                        if is_new_bar:
                            self._enqueue_pair(pair, "rest_candle")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "REST candle poll error",
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
                await asyncio.sleep(interval)

    async def _health_monitor(self) -> None:
        """Monitor system health and trigger recovery actions."""
        while self._running:
            try:
                await asyncio.sleep(
                    self.config.monitoring.health_check_interval
                )

                # NOTE: The WS client and main.py task wrapper already handle reconnection/restarts.
                # Do not spawn a second WS loop here (it can double-subscribe and corrupt state).
                if self.ws_client and not self.ws_client.is_connected:
                    logger.warning("WebSocket disconnected; waiting for reconnect/restart")

                # Check data freshness (5-min threshold — low-volume pairs are naturally slower)
                stale_pairs = [
                    pair for pair in self.pairs
                    if self.market_data.is_stale(pair, max_age_seconds=600)
                ]
                if stale_pairs:
                    logger.warning(
                        "Stale data detected",
                        pairs=stale_pairs,
                    )
                    # Attempt REST refresh for stale pairs
                    for pair in stale_pairs:
                        try:
                            ohlc = await self.rest_client.get_ohlc(pair, interval=1)
                            if ohlc:
                                await self.market_data.warmup(pair, ohlc)
                        except Exception as e:
                            logger.debug("REST refresh for stale pair failed", pair=pair, error=repr(e))

                # Circuit breakers (auto-pause) for safer unattended operation.
                await self._apply_circuit_breakers(stale_pairs)

                # Log health status
                await self.db.insert_metric(
                    "uptime_seconds",
                    time.time() - self._start_time,
                    tenant_id=self.tenant_id,
                )
                await self.db.insert_metric(
                    "open_positions",
                    len(await self.db.get_open_trades(tenant_id=self.tenant_id)),
                    tenant_id=self.tenant_id,
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Health monitor error",
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of old data."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Every hour
                await self.db.cleanup_old_data(
                    self.config.monitoring.metrics_retention_hours
                )
                # ES index retention cleanup
                if self.es_client:
                    try:
                        deleted = await self.es_client.cleanup_old_indices()
                        if deleted:
                            logger.info("ES index cleanup", deleted=deleted)
                    except Exception:
                        pass
                logger.info("Database cleanup completed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Cleanup error",
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )

    def _enqueue_pair(self, pair: str, reason: str = "") -> None:
        """Enqueue a pair for event-driven scanning (deduped)."""
        if pair in self._pending_scan_pairs:
            return
        self._pending_scan_pairs.add(pair)
        try:
            self._scan_queue.put_nowait(pair)
        except asyncio.QueueFull:
            self._pending_scan_pairs.discard(pair)

    async def _collect_scan_pairs(self) -> tuple[list, bool]:
        """
        Collect pairs to scan with adaptive timeout.
        High event frequency → shorter wait (more responsive).
        Low event frequency → longer wait (save CPU).
        Returns (pairs, from_event_queue).
        """
        # Adaptive scan interval based on recent event frequency
        now = time.time()
        if now - self._event_window_start > 60:
            self._recent_event_count = 0
            self._event_window_start = now
        # Scale timeout: many events → faster (min 5s), few events → configured interval
        events_per_min = self._recent_event_count
        if events_per_min > 20:
            adaptive_timeout = max(5, self.scan_interval // 3)
        elif events_per_min > 5:
            adaptive_timeout = max(10, self.scan_interval // 2)
        else:
            adaptive_timeout = self.scan_interval

        pairs = set()
        try:
            pair = await asyncio.wait_for(
                self._scan_queue.get(), timeout=adaptive_timeout
            )
            pairs.add(pair)
            self._recent_event_count += 1
            while True:
                pair = self._scan_queue.get_nowait()
                pairs.add(pair)
                self._recent_event_count += 1
        except asyncio.TimeoutError:
            return list(self.pairs), False
        except asyncio.QueueEmpty:
            pass
        for p in pairs:
            self._pending_scan_pairs.discard(p)
        return list(pairs), True

    # ------------------------------------------------------------------
    # WebSocket Handlers
    # ------------------------------------------------------------------

    def _parse_ts(self, ts_value) -> float:
        """Parse Kraken timestamp (ISO string or float) to epoch float."""
        if isinstance(ts_value, (int, float)):
            return float(ts_value)
        if isinstance(ts_value, str):
            try:
                from datetime import datetime, timezone
                # Handle Kraken's ISO format: "2026-02-07T02:00:00.099318Z"
                dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return time.time()

    async def _handle_ticker(self, message: Dict[str, Any]) -> None:
        """Process ticker updates — updates latest price in-place (no new bars)."""
        try:
            data = message.get("data", [])
            if isinstance(data, list):
                for tick in data:
                    symbol = tick.get("symbol", "")
                    if symbol:
                        self.market_data.update_ticker(symbol, tick)
                        # S1 FIX: Only update the CLOSE of the current bar in-place.
                        # NEVER inject fake bars — that destroys ATR, volume, and all indicators.
                        last = tick.get("last")
                        if last and float(last) > 0:
                            prev = self.market_data.get_latest_price(symbol)
                            await self.market_data.update_latest_close(symbol, float(last))
                            if prev > 0:
                                move = abs(float(last) - prev) / prev
                                if move >= self._event_price_move_pct:
                                    self._enqueue_pair(symbol, "price_move")
        except Exception as e:
            logger.warning("Ticker handler error", error=str(e))

    async def _handle_ohlc(self, message: Dict[str, Any]) -> None:
        """Process OHLC candle updates from WebSocket."""
        try:
            data = message.get("data", [])
            if isinstance(data, list):
                for candle in data:
                    symbol = candle.get("symbol", "")
                    if symbol:
                        is_new_bar = await self.market_data.update_bar(symbol, {
                            "time": self._parse_ts(candle.get("interval_begin", candle.get("timestamp", time.time()))),
                            "open": float(candle.get("open", 0)),
                            "high": float(candle.get("high", 0)),
                            "low": float(candle.get("low", 0)),
                            "close": float(candle.get("close", 0)),
                            "volume": float(candle.get("volume", 0)),
                            "vwap": float(candle.get("vwap", 0)),
                        })
                        if is_new_bar:
                            self._enqueue_pair(symbol, "bar_close")
                            # Index candle to ES
                            try:
                                if self.market_data_indexer:
                                    self.market_data_indexer.index_candle(symbol, {
                                        "time": self._parse_ts(candle.get("interval_begin", candle.get("timestamp", time.time()))),
                                        "open": float(candle.get("open", 0)),
                                        "high": float(candle.get("high", 0)),
                                        "low": float(candle.get("low", 0)),
                                        "close": float(candle.get("close", 0)),
                                        "volume": float(candle.get("volume", 0)),
                                        "vwap": float(candle.get("vwap", 0)),
                                    })
                            except Exception:
                                pass
        except Exception as e:
            logger.warning("OHLC handler error", error=str(e))

    async def _handle_book(self, message: Dict[str, Any]) -> None:
        """Process order book updates from WebSocket."""
        try:
            data = message.get("data", [])
            if isinstance(data, list):
                for book_update in data:
                    symbol = book_update.get("symbol", "")
                    if symbol:
                        self.market_data.update_order_book(symbol, book_update)

                        # Run order book analysis
                        if self.order_book_analyzer:
                            bids = book_update.get("bids", [])
                            asks = book_update.get("asks", [])
                            price = self.market_data.get_latest_price(symbol)
                            analysis = self.order_book_analyzer.analyze(
                                symbol, bids, asks, price
                            )
                            if analysis:
                                analysis_dict = analysis.to_dict()
                                self.market_data.update_order_book_analysis(
                                    symbol, analysis_dict
                                )
                                # Index orderbook snapshot to ES
                                try:
                                    if self.market_data_indexer:
                                        self.market_data_indexer.index_orderbook(symbol, analysis_dict)
                                except Exception:
                                    pass
        except Exception as e:
            logger.debug("Book handler error", error=str(e))

    async def _handle_trade(self, message: Dict[str, Any]) -> None:
        """Process trade stream updates."""
        pass  # Trade stream processing for future use

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prediction_features(
        self, signal
    ) -> Dict[str, Any]:
        """Build feature dict for AI predictor from confluence signal."""
        if not self.predictor:
            return {}
        # S7 FIX: Average overlapping numeric keys instead of overwriting
        metadata = {}
        counts = {}
        for s in signal.signals:
            if s.direction == signal.direction:  # Only use agreeing signals
                for k, v in s.metadata.items():
                    if k in metadata and isinstance(v, (int, float)) and isinstance(metadata[k], (int, float)):
                        metadata[k] = metadata[k] + v
                        counts[k] = counts.get(k, 1) + 1
                    else:
                        metadata[k] = v
        for k in counts:
            metadata[k] = metadata[k] / counts[k]

        features = self.predictor.features.feature_dict_from_signals(
            metadata,
            obi=(signal.book_score if getattr(signal, "book_score", 0.0) else signal.obi),
            spread=self.market_data.get_spread(signal.pair),
        )
        return features

    def get_algorithm_stats(self) -> List[Dict[str, Any]]:
        """Return full algorithm transparency list for the dashboard."""
        stats: List[Dict[str, Any]] = []
        if self.confluence:
            stats.extend(self.confluence.get_strategy_stats())
            obi_enabled = getattr(self.confluence, "obi_threshold", 0) > 0
            book_enabled = getattr(self.confluence, "book_score_threshold", 0) > 0
            stats.append({
                "name": "order_book_imbalance",
                "enabled": bool(obi_enabled),
                "weight": float(getattr(self.confluence, "obi_weight", 0.0)),
                "trades": 0,
                "win_rate": None,
                "total_pnl": None,
                "avg_pnl": None,
                "kind": "filter",
                "note": "confirmation filter"
                        + (" (weighted)" if getattr(self.confluence, "obi_counts_as_confluence", False) else ""),
            })
            stats.append({
                "name": "order_book_microstructure",
                "enabled": bool(book_enabled),
                "weight": 0.0,
                "trades": 0,
                "win_rate": None,
                "total_pnl": None,
                "avg_pnl": None,
                "kind": "filter",
                "note": "book score confirmation",
            })
            stats.append({
                "name": "regime_detector",
                "enabled": True,
                "weight": 0.0,
                "trades": 0,
                "win_rate": None,
                "total_pnl": None,
                "avg_pnl": None,
                "kind": "model",
                "note": "trend/volatility regime",
            })
        stats.append({
            "name": "ai_predictor",
            # Consider AI online when either:
            # - TFLite model is loaded, or
            # - heuristic predictor is available, or
            # - continuous learner is active.
            "enabled": bool(self.predictor or self.continuous_learner),
            "weight": 0.0,
            "trades": 0,
            "win_rate": None,
            "total_pnl": None,
            "avg_pnl": None,
            "kind": "model",
            "note": (
                "tflite signal scoring"
                if bool(self.predictor and self.predictor.is_model_loaded)
                else "heuristic fallback + continuous learner"
            ),
        })
        return stats
