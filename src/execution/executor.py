"""
Trade Executor - Unified order management and fill processing.

Handles the full lifecycle of trade execution: order placement,
fill monitoring, position tracking, and stop management. Supports
both paper and live trading modes.

# ENHANCEMENT: Added paper trading engine with realistic simulation
# ENHANCEMENT: Added slippage estimation model
# ENHANCEMENT: Added order retry with price adjustment
# ENHANCEMENT: Added unified fill processor for DB <-> RAM sync
# ENHANCEMENT: Support for Limit Orders to control execution price
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable

from src.ai.confluence import ConfluenceSignal
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.ml.continuous_learner import ContinuousLearner
from src.exchange.exceptions import (
    PermanentExchangeError,
    RateLimitError,
    TransientExchangeError,
)
from src.exchange.market_data import MarketDataCache
from src.execution.risk_manager import RiskManager
from src.strategies.base import SignalDirection
from src.utils.indicators import order_book_imbalance

logger = get_logger("executor")


class TradeExecutor:
    """
    Production trade execution engine.
    
    Manages the complete trade lifecycle:
    1. Signal validation -> Risk check -> Position sizing
    2. Order placement (paper or live)
    3. Fill monitoring and processing
    4. Stop loss management (trailing + breakeven)
    5. Position closure and P&L recording
    
    # ENHANCEMENT: Added order splitting for large positions
    # ENHANCEMENT: Added fee estimation and tracking
    # ENHANCEMENT: Added execution quality metrics
    """

    def __init__(
        self,
        rest_client: Any,
        market_data: MarketDataCache,
        risk_manager: RiskManager,
        db: DatabaseManager,
        mode: str = "paper",
        maker_fee: float = 0.0016,
        taker_fee: float = 0.0026,
        post_only: bool = False,
        tenant_id: Optional[str] = "default",
        limit_chase_attempts: int = 2,
        limit_chase_delay_seconds: float = 2.0,
        limit_fallback_to_market: bool = True,
        es_client: Optional[Any] = None,
        strategy_result_cb: Optional[Callable[[str, float, str, str], None]] = None,
        max_trades_per_hour: int = 0,
        quiet_hours_utc: Optional[tuple] = None,
        smart_exit_enabled: bool = False,
        smart_exit_tiers: Optional[list] = None,
        max_trade_duration_hours: int = 24,
        correlation_groups: Optional[Dict[str, str]] = None,
        max_per_correlation_group: int = 2,
        liquidity_sizing_enabled: bool = False,
        liquidity_max_impact_pct: float = 0.10,
        liquidity_min_depth_ratio: float = 3.0,
    ):
        self.rest_client = rest_client
        self.market_data = market_data
        self.risk_manager = risk_manager
        self.db = db
        self.mode = mode  # "paper" or "live"
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.post_only = post_only
        self.tenant_id = tenant_id or "default"
        self.limit_chase_attempts = max(0, int(limit_chase_attempts))
        self.limit_chase_delay_seconds = max(0.0, float(limit_chase_delay_seconds))
        self.limit_fallback_to_market = bool(limit_fallback_to_market)
        self.es_client = es_client
        self._strategy_result_cb = strategy_result_cb
        self.max_trades_per_hour = max(0, int(max_trades_per_hour or 0))
        self.quiet_hours_utc = tuple(quiet_hours_utc) if quiet_hours_utc else ()
        self.max_trade_duration_hours = max(1, int(max_trade_duration_hours))
        self._smart_exit_constructor_flag = smart_exit_enabled
        self._smart_exit_constructor_tiers = list(smart_exit_tiers) if smart_exit_tiers else []

        self.continuous_learner: Optional[ContinuousLearner] = None
        # Optional reference to confluence detector for hold-duration queries.
        # Set by the engine after construction.
        self._confluence: Optional[Any] = None

        # Correlation groups: pairs in the same group share a single slot
        # to prevent concentrated directional exposure.
        self._correlation_groups: Dict[str, str] = correlation_groups or {
            "BTC/USD": "btc",
            "ETH/USD": "major",
            "SOL/USD": "alt_l1",
            "AVAX/USD": "alt_l1",
            "DOT/USD": "alt_l1",
            "ADA/USD": "alt_l1",
            "XRP/USD": "alt_payment",
            "LINK/USD": "alt_oracle",
        }
        self._max_per_correlation_group = max(1, int(max_per_correlation_group or 1))

        # Liquidity-aware sizing config
        self._liquidity_sizing_enabled = bool(liquidity_sizing_enabled)
        self._liquidity_max_impact_pct = float(liquidity_max_impact_pct)
        self._liquidity_min_depth_ratio = float(liquidity_min_depth_ratio)

        # Per-trade locks to prevent concurrent management of the same position
        self._position_locks: Dict[str, asyncio.Lock] = {}

        # Note: safe under asyncio single-threaded event loop — increments
        # are atomic between await points.
        self._execution_stats = {
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_cancelled": 0,
            "total_slippage": 0.0,
            "total_fees": 0.0,
        }
        # Small TTL cache to avoid hitting SQLite for every candidate signal
        # when max_trades_per_hour is enabled.
        self._recent_trades_cache_value: int = 0
        self._recent_trades_cache_at: float = 0.0
        self._recent_trades_cache_ttl_seconds: float = 5.0

        # Smart Exit config — loaded lazily from config on first use
        self._smart_exit_enabled: Optional[bool] = None
        self._smart_exit_tiers: Optional[list] = None
        self.session_analyzer = None
        self._event_calendar = None

    def set_continuous_learner(self, learner: ContinuousLearner) -> None:
        """Attach the continuous learner for online ML updates."""
        self.continuous_learner = learner

    def set_event_calendar(self, calendar) -> None:
        """Attach event calendar for blackout gating."""
        self._event_calendar = calendar

    def set_es_client(self, es_client: Any) -> None:
        """Attach Elasticsearch client for trade event mirroring."""
        self.es_client = es_client

    @staticmethod
    def _parse_meta(raw: Any) -> dict:
        """Parse trade metadata from JSON string or dict, returning empty dict on failure."""
        if not raw:
            return {}
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        except Exception:
            return {}

    @staticmethod
    def _shift_levels_to_fill(
        planned_entry: float,
        fill_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[float, float]:
        """
        Shift SL/TP by entry delta so risk distances stay consistent after fill.

        This prevents unintentional stop tightening/widening when the actual fill
        differs from the signal entry.
        """
        if planned_entry <= 0 or fill_price <= 0:
            return stop_loss, take_profit

        shift = fill_price - planned_entry
        adj_sl = stop_loss
        adj_tp = take_profit
        if stop_loss > 0:
            adj_sl = max(stop_loss + shift, 0.0)
        if take_profit > 0:
            adj_tp = max(take_profit + shift, 0.0)
        return adj_sl, adj_tp

    async def reinitialize_positions(self) -> None:
        """Restore position and stop-loss state from database after restart."""
        open_trades = await self.db.get_open_trades(tenant_id=self.tenant_id)
        for trade in open_trades:
            trade_id = trade["trade_id"]
            pair = trade["pair"]
            side = trade["side"]
            entry_price = trade["entry_price"]
            sl = trade["stop_loss"]
            
            # Use metadata to get size_usd and trailing state if available
            size_usd = 0.0
            trailing_high = 0.0
            trailing_low = float("inf")
            
            meta = self._parse_meta(trade.get("metadata"))
            if meta:
                size_usd = meta.get("size_usd", 0.0)
                # Restore stop loss state
                if "stop_loss_state" in meta:
                    sl_state = meta["stop_loss_state"]
                    trailing_high = sl_state.get("trailing_high", 0.0)
                    trailing_low = sl_state.get("trailing_low", float("inf"))
            
            if size_usd == 0.0:
                size_usd = entry_price * trade["quantity"]

            # Re-register with RiskManager (is_restart=True skips daily trade
            # counter increment since these are existing positions being restored)
            self.risk_manager.register_position(
                trade_id,
                pair,
                side,
                entry_price,
                size_usd,
                strategy=trade.get("strategy"),
                is_restart=True,
            )
            # Restore stop loss state
            if sl > 0:
                self.risk_manager.initialize_stop_loss(
                    trade_id, entry_price, sl, side, trailing_high, trailing_low
                )
            
            logger.info(
                "Restored position state",
                trade_id=trade_id, pair=pair, sl=sl
            )

    async def reconcile_exchange_positions(
        self, auto_close_ghost_after_hours: float = 0,
    ) -> None:
        """Compare DB open trades against exchange open orders at startup.

        Detects ghost positions (DB says open but exchange has no matching
        order) and orphan orders (exchange has an open order not tracked in
        the DB).

        If *auto_close_ghost_after_hours* > 0, ghost positions whose entry
        is older than that many hours are automatically marked closed in the
        DB at their entry price (zero P&L).  This prevents the bot from
        endlessly managing a non-existent exchange position.
        """
        if self.mode != "live":
            logger.info("Skipping exchange position reconciliation (mode=%s)", self.mode)
            return

        if not self.rest_client:
            logger.info("Skipping exchange position reconciliation (no rest_client)")
            return

        try:
            # Fetch exchange open orders
            exchange_response = await self.rest_client.get_open_orders()
            exchange_orders: Dict[str, Any] = exchange_response.get("open", {})

            # Fetch DB open trades
            db_trades = await self.db.get_open_trades(tenant_id=self.tenant_id)

            # Build set of order_txids tracked in DB trades
            db_txids: set[str] = set()
            trades_without_txid: list[str] = []
            txid_to_trade: Dict[str, Dict[str, Any]] = {}

            for trade in db_trades:
                trade_id = trade["trade_id"]
                txid = None
                meta = self._parse_meta(trade.get("metadata"))
                if meta:
                    txid = meta.get("order_txid")

                if txid:
                    db_txids.add(txid)
                    txid_to_trade[txid] = trade
                else:
                    trades_without_txid.append(trade_id)

            # Ghost positions: DB trade references an order_txid that the
            # exchange no longer shows as open.  Note — filled orders also
            # disappear from open orders, so a ghost warning does NOT always
            # mean something is wrong; it simply flags trades worth checking.
            exchange_txids = set(exchange_orders.keys())
            ghost_txids = db_txids - exchange_txids
            auto_closed = 0

            for txid in ghost_txids:
                trade = txid_to_trade.get(txid)
                trade_id = trade["trade_id"] if trade else "unknown"

                # Determine age of the trade
                trade_age_hours = 0.0
                if trade:
                    try:
                        created = trade.get("created_at", "")
                        if created:
                            created_dt = datetime.fromisoformat(
                                str(created).replace("Z", "+00:00")
                            )
                            trade_age_hours = (
                                datetime.now(timezone.utc) - created_dt
                            ).total_seconds() / 3600.0
                    except Exception:
                        pass

                if (
                    auto_close_ghost_after_hours > 0
                    and trade_age_hours >= auto_close_ghost_after_hours
                    and trade
                ):
                    entry_price = float(trade.get("entry_price", 0) or 0)
                    logger.warning(
                        "Auto-closing stale ghost position",
                        trade_id=trade_id,
                        order_txid=txid,
                        pair=trade.get("pair"),
                        age_hours=round(trade_age_hours, 1),
                    )
                    try:
                        await self.db.update_trade(trade_id, {
                            "status": "closed",
                            "exit_price": entry_price,
                            "pnl": 0.0,
                            "close_reason": "ghost_reconciliation",
                        })
                        self.risk_manager.close_position(trade_id, 0.0)
                        auto_closed += 1
                    except Exception as e:
                        logger.error(
                            "Failed to auto-close ghost position",
                            trade_id=trade_id, error=repr(e),
                        )
                else:
                    logger.info(
                        "Potential ghost position: DB trade references order_txid "
                        "not found in exchange open orders (may be filled)",
                        order_txid=txid,
                        trade_id=trade_id,
                        age_hours=round(trade_age_hours, 1),
                        tenant_id=self.tenant_id,
                    )

            # Orphan orders: exchange has an open order that no DB trade
            # references.
            orphan_txids = exchange_txids - db_txids
            for txid in orphan_txids:
                order_info = exchange_orders[txid]
                logger.warning(
                    "Potential orphan order: exchange has open order not "
                    "tracked in DB",
                    order_txid=txid,
                    pair=order_info.get("descr", {}).get("pair", "unknown"),
                    order_type=order_info.get("descr", {}).get("type", "unknown"),
                    tenant_id=self.tenant_id,
                )

            if trades_without_txid:
                logger.info(
                    "DB trades without order_txid in metadata (cannot reconcile)",
                    count=len(trades_without_txid),
                    trade_ids=trades_without_txid[:10],
                )

            logger.info(
                "Exchange position reconciliation complete",
                db_open_trades=len(db_trades),
                exchange_open_orders=len(exchange_orders),
                ghost_candidates=len(ghost_txids),
                ghost_auto_closed=auto_closed,
                orphan_candidates=len(orphan_txids),
            )

        except Exception as e:
            logger.error(
                "Exchange position reconciliation failed (non-blocking)",
                error=repr(e),
            )

    async def execute_signal(
        self, signal: ConfluenceSignal
    ) -> Optional[str]:
        """
        Execute a confluence signal through the full pipeline.

        Pipeline:
        1. Validate signal quality and age
        2. Check rate limits, duplicate positions, correlation limits
        3. Calculate position size and place order
        4. Record trade and register with risk manager
        5. Capture entry telemetry (ML features, order book)

        Returns trade_id if executed, None if rejected.
        """
        # Stage 1: Signal validation
        effective_confidence = self._validate_signal(signal)
        if effective_confidence is None:
            return None

        # Stage 2: Pre-trade gates
        side = "buy" if signal.direction == SignalDirection.LONG else "sell"
        primary_strategy = self._primary_strategy(signal)

        if not await self._check_gates(signal, side, primary_strategy):
            return None

        # Stage 3: Position sizing and order fill
        fill = await self._size_and_fill(signal, side)
        if fill is None:
            return None
        trade_id, fill_price, filled_units, partial_fill, entry_fee, size_result, adjusted_sl, adjusted_tp = fill

        # Stage 4: Register with risk manager FIRST (before DB insert) so a
        # crash between DB write and registration can't leave phantom positions.
        slippage = abs(fill_price - signal.entry_price) / signal.entry_price if signal.entry_price > 0 else 0.0
        filled_size_usd = filled_units * fill_price

        self.risk_manager.initialize_stop_loss(trade_id, fill_price, adjusted_sl, side)
        self.risk_manager.register_position(
            trade_id, signal.pair, side,
            fill_price, filled_size_usd, strategy=primary_strategy,
        )

        # Stage 5: Record trade in DB
        trade_record = await self._record_trade(
            signal, trade_id, side, primary_strategy,
            fill_price, filled_units, partial_fill, entry_fee,
            size_result, adjusted_sl, adjusted_tp, slippage, filled_size_usd,
        )

        # Stage 6: Entry telemetry (best-effort, non-blocking)
        await self._capture_entry_telemetry(signal, trade_id)
        if self.mode == "live" and adjusted_sl > 0:
            await self._place_exchange_stop(
                trade_id, signal.pair, side, adjusted_sl, filled_units,
            )

        # Update execution stats
        self._execution_stats["orders_placed"] += 1
        self._execution_stats["orders_filled"] += 1
        self._execution_stats["total_slippage"] += slippage
        self._execution_stats["total_fees"] += trade_record["metadata"]["fees"]

        await self.db.log_thought(
            "trade",
            f"{'📈' if side == 'buy' else '📉'} {side.upper()} {signal.pair} @ "
            f"${fill_price:.2f} (Limit) | Size: ${filled_size_usd:.2f} | "
            f"SL: ${adjusted_sl:.2f} | TP: ${adjusted_tp:.2f} | "
            f"Confluence: {signal.confluence_count} | "
            f"{'SURE FIRE' if signal.is_sure_fire else 'Standard'}",
            severity="info",
            metadata=trade_record["metadata"],
            tenant_id=self.tenant_id,
        )

        logger.info(
            "Trade executed",
            trade_id=trade_id,
            pair=signal.pair,
            side=side,
            price=fill_price,
            size_usd=round(filled_size_usd, 2),
            mode=self.mode,
        )

        return trade_id

    # ------------------------------------------------------------------
    # execute_signal sub-stages
    # ------------------------------------------------------------------

    def _validate_signal(self, signal: ConfluenceSignal) -> Optional[float]:
        """Validate signal quality and apply age-based confidence decay.

        Returns effective confidence if the signal passes all checks,
        or None if the signal should be rejected.
        """
        if signal.direction == SignalDirection.NEUTRAL:
            return None

        signal_age_seconds = 0.0
        try:
            sig_ts = datetime.fromisoformat(signal.timestamp.replace("Z", "+00:00"))
            signal_age_seconds = (datetime.now(timezone.utc) - sig_ts).total_seconds()
        except Exception:
            pass

        effective_confidence = signal.confidence
        if signal_age_seconds > 5:
            decay = min((signal_age_seconds - 5) * 0.02, 0.30)
            effective_confidence = max(signal.confidence - decay, 0.0)
        if signal_age_seconds > 60:
            return None

        return effective_confidence if effective_confidence >= 0.50 else None

    async def _check_gates(
        self, signal: ConfluenceSignal, side: str, primary_strategy: str,
    ) -> bool:
        """Check all pre-trade gates: quiet hours, rate throttle,
        duplicate pair, correlation limits, and strategy cooldown.

        Returns True if all gates pass, False if the trade is blocked.
        """
        # Event calendar blackout
        if self._event_calendar:
            is_blackout, event_name = self._event_calendar.is_blackout()
            if is_blackout:
                await self.db.log_thought(
                    "risk",
                    f"Trade blocked: macro event blackout ({event_name})",
                    severity="warning",
                    metadata={"pair": signal.pair, "event": event_name},
                    tenant_id=self.tenant_id,
                )
                return False

        # Quiet hours filter
        if self.quiet_hours_utc:
            if datetime.now(timezone.utc).hour in self.quiet_hours_utc:
                return False

        # Trade-rate throttle
        if self.max_trades_per_hour > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            recent_trades = await self._get_recent_trades_count(cutoff)
            if recent_trades >= self.max_trades_per_hour:
                await self.db.log_thought(
                    "risk",
                    f"Trade blocked: trade-rate limit reached "
                    f"({recent_trades}/{self.max_trades_per_hour} in last hour)",
                    severity="warning",
                    metadata={"pair": signal.pair, "cutoff": cutoff},
                    tenant_id=self.tenant_id,
                )
                return False

        # Fetch open trades once for duplicate and correlation checks
        all_open = await self.db.get_open_trades(tenant_id=self.tenant_id)

        # Block duplicate pair
        if any(t["pair"] == signal.pair for t in all_open):
            return False

        # Correlation guard
        group = self._correlation_groups.get(signal.pair)
        if group:
            group_count = sum(
                1 for t in all_open
                if self._correlation_groups.get(t.get("pair")) == group
            )
            if group_count >= self._max_per_correlation_group:
                return False

        # Strategy cooldown
        if self.risk_manager.is_strategy_on_cooldown(signal.pair, primary_strategy, side):
            await self.db.log_thought(
                "risk",
                f"Trade blocked: {primary_strategy} cooldown active for {signal.pair}",
                severity="warning",
                metadata={"pair": signal.pair, "strategy": primary_strategy},
                tenant_id=self.tenant_id,
            )
            return False

        return True

    async def _size_and_fill(
        self, signal: ConfluenceSignal, side: str,
    ) -> Optional[tuple]:
        """Calculate position size, determine limit price, and place order.

        Returns (trade_id, fill_price, filled_units, partial_fill,
                 entry_fee, size_result, adjusted_sl, adjusted_tp) on success,
        or None if sizing is rejected or the fill fails.
        """
        stats = await self.db.get_performance_stats(tenant_id=self.tenant_id)
        total_trades = stats.get("total_trades", 0)

        if total_trades >= 50:
            win_rate = max(stats.get("win_rate", 0.5), 0.35)
            avg_win = max(stats.get("avg_win", 1.0), 0.01)
            avg_loss = max(abs(stats.get("avg_loss", -1.0)), 0.01)
            win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.5
        else:
            win_rate = 0.50
            win_loss_ratio = 1.5

        spread_pct = self.market_data.get_spread(signal.pair) if self.market_data else 0.0
        session_multiplier = 1.0
        if getattr(self, "session_analyzer", None):
            session_multiplier = float(
                self.session_analyzer.get_multiplier(datetime.now(timezone.utc).hour)
            )

        # Structural stop loss: use swing-based SL if computed by confluence
        effective_sl = signal.stop_loss
        if getattr(signal, "structural_sl", None) and signal.structural_sl > 0:
            effective_sl = signal.structural_sl

        # Liquidity depth data for liquidity-aware sizing
        bid_depth_usd = 0.0
        ask_depth_usd = 0.0
        liquidity_enabled = getattr(self, "_liquidity_sizing_enabled", False)
        liquidity_max_impact = getattr(self, "_liquidity_max_impact_pct", 0.10)
        liquidity_min_ratio = getattr(self, "_liquidity_min_depth_ratio", 3.0)
        if liquidity_enabled and self.market_data:
            order_book = self.market_data.get_order_book(signal.pair)
            if order_book:
                bids = order_book.get("bids", [])
                asks = order_book.get("asks", [])
                try:
                    for b in bids[:10]:
                        if isinstance(b, (list, tuple)) and len(b) >= 2:
                            bid_depth_usd += float(b[0]) * float(b[1])
                    for a in asks[:10]:
                        if isinstance(a, (list, tuple)) and len(a) >= 2:
                            ask_depth_usd += float(a[0]) * float(a[1])
                except (ValueError, TypeError, IndexError):
                    pass

        size_result = self.risk_manager.calculate_position_size(
            pair=signal.pair,
            entry_price=signal.entry_price,
            stop_loss=effective_sl,
            take_profit=signal.take_profit,
            win_rate=win_rate,
            avg_win_loss_ratio=win_loss_ratio,
            confidence=signal.confidence,
            spread_pct=spread_pct,
            vol_regime=getattr(signal, "volatility_regime", "") or "",
            vol_level=getattr(signal, "vol_level", 0.5),
            vol_expanding=getattr(signal, "vol_expanding", False),
            session_multiplier=session_multiplier,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            liquidity_sizing_enabled=liquidity_enabled,
            liquidity_max_impact_pct=liquidity_max_impact,
            liquidity_min_depth_ratio=liquidity_min_ratio,
        )

        if not size_result.allowed:
            await self.db.log_thought(
                "risk",
                f"Trade blocked: {size_result.reason}",
                severity="warning",
                metadata={"pair": signal.pair, "signal": signal.to_dict()},
                tenant_id=self.tenant_id,
            )
            return None

        # Determine limit price: buy at ask, sell at bid
        ticker = self.market_data.get_ticker(signal.pair)
        limit_price = signal.entry_price
        if ticker:
            try:
                if side == "buy":
                    limit_price = float(ticker['a'][0])
                else:
                    limit_price = float(ticker['b'][0])
            except (KeyError, IndexError, ValueError):
                pass

        # Place order
        trade_id = f"T-{uuid.uuid4().hex[:12]}"
        partial_fill = False
        filled_units = size_result.size_units
        entry_fee = 0.0

        if self.mode == "paper":
            fill_price = await self._paper_fill(signal.pair, side, limit_price)
        else:
            fill_price, filled_units, partial_fill, entry_fee = await self._live_fill(
                signal.pair, side, "limit", size_result.size_units,
                trade_id, price=limit_price, post_only=self.post_only,
            )

        if fill_price is None or not filled_units or filled_units <= 0:
            await self.db.log_thought(
                "execution",
                f"Order fill failed for {signal.pair}",
                severity="error",
                tenant_id=self.tenant_id,
            )
            return None

        adjusted_sl, adjusted_tp = self._shift_levels_to_fill(
            planned_entry=signal.entry_price,
            fill_price=fill_price,
            stop_loss=effective_sl,
            take_profit=signal.take_profit,
        )

        return (trade_id, fill_price, filled_units, partial_fill,
                entry_fee, size_result, adjusted_sl, adjusted_tp)

    async def _record_trade(
        self,
        signal: ConfluenceSignal,
        trade_id: str,
        side: str,
        primary_strategy: str,
        fill_price: float,
        filled_units: float,
        partial_fill: bool,
        entry_fee: float,
        size_result: Any,
        adjusted_sl: float,
        adjusted_tp: float,
        slippage: float,
        filled_size_usd: float,
    ) -> dict:
        """Build trade record, insert into DB, and emit trade event.

        Returns the trade_record dict (for downstream metadata access).
        """
        if entry_fee and entry_fee > 0:
            fees = entry_fee
            entry_fee_rate = entry_fee / filled_size_usd if filled_size_usd > 0 else 0.0
        else:
            entry_fee_rate = self.maker_fee if (self.post_only and self.mode == "live") else self.taker_fee
            fees = filled_size_usd * entry_fee_rate

        trade_record = {
            "trade_id": trade_id,
            "pair": signal.pair,
            "side": side,
            "entry_price": fill_price,
            "quantity": filled_units,
            "status": "open",
            "strategy": primary_strategy,
            "confidence": signal.confidence,
            "stop_loss": adjusted_sl,
            "take_profit": adjusted_tp,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "confluence_count": signal.confluence_count,
                "is_sure_fire": signal.is_sure_fire,
                "obi": signal.obi,
                "book_score": getattr(signal, "book_score", 0.0),
                "size_usd": round(filled_size_usd, 2),
                "risk_amount": round(size_result.risk_amount, 2),
                "kelly_fraction": size_result.kelly_fraction,
                "slippage": slippage,
                "fees": fees,
                "entry_fee": fees,
                "entry_fee_rate": entry_fee_rate,
                "exit_fee_rate": self.taker_fee,
                "requested_units": size_result.size_units,
                "filled_units": filled_units,
                "partial_fill": partial_fill,
                "mode": self.mode,
                "order_type": "limit",
                "post_only": self.post_only,
                "planned_entry_price": signal.entry_price,
                "planned_stop_loss": signal.stop_loss,
                "planned_take_profit": signal.take_profit,
                "trend_regime": getattr(signal, "regime", "") or "",
                "vol_regime": getattr(signal, "volatility_regime", "") or "",
                "vol_level": round(getattr(signal, "vol_level", 0.5), 4),
                "vol_expanding": getattr(signal, "vol_expanding", False),
                "atr_pct": round(float((getattr(signal, "core_indicators", None) or {}).get("atr_pct", 0) or 0), 6),
            },
        }

        await self.db.insert_trade(trade_record, tenant_id=self.tenant_id)
        self._enqueue_trade_event(
            "opened",
            {
                "trade_id": trade_id,
                "tenant_id": self.tenant_id,
                "pair": signal.pair,
                "side": side,
                "strategy": primary_strategy,
                "mode": self.mode,
                "status": "open",
                "entry_price": fill_price,
                "quantity": filled_units,
                "size_usd": filled_size_usd,
                "stop_loss": adjusted_sl,
                "take_profit": adjusted_tp,
                "confidence": signal.confidence,
            },
        )
        return trade_record

    # Expected ML feature keys and their safe defaults (from predictor.py).
    _ML_FEATURE_DEFAULTS: Dict[str, float] = {
        "rsi": 50.0, "ema_ratio": 1.0, "bb_position": 0.5, "adx": 0.0,
        "volume_ratio": 1.0, "obi": 0.0, "atr_pct": 0.02,
        "momentum_score": 0.0, "trend_strength": 0.0, "spread_pct": 0.0,
        "trend_regime_encoded": 1.0, "vol_regime_encoded": 1.0,
    }

    async def _capture_entry_telemetry(
        self, signal: ConfluenceSignal, trade_id: str,
    ) -> None:
        """Record ML features and order book snapshot at entry (best-effort).

        Order book data is computed FIRST so that entry-time OBI and spread
        can override the prediction-time values in the ML feature vector.
        """
        # ------------------------------------------------------------------
        # Step 1: Compute entry-time order book data FIRST
        # ------------------------------------------------------------------
        entry_obi: Optional[float] = None
        entry_spread: Optional[float] = None
        try:
            book = self.market_data.get_order_book(signal.pair) if self.market_data else {}
            bids = (book.get("bids", []) or [])[:10]
            asks = (book.get("asks", []) or [])[:10]

            def _vol_sum(levels: List[Any]) -> float:
                total = 0.0
                for lvl in levels:
                    try:
                        if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                            total += float(lvl[1])
                        elif isinstance(lvl, dict):
                            for key in ("volume", "qty", "size", "q"):
                                if key in lvl:
                                    total += float(lvl[key])
                                    break
                    except Exception:
                        continue
                return total

            bid_vol = _vol_sum(bids)
            ask_vol = _vol_sum(asks)
            entry_obi = order_book_imbalance(bid_vol, ask_vol)
            entry_spread = self.market_data.get_spread(signal.pair) if self.market_data else 0.0

            await self.db.insert_order_book_snapshot(
                pair=signal.pair,
                bid_volume=bid_vol,
                ask_volume=ask_vol,
                obi=entry_obi,
                spread=entry_spread,
                whale_detected=0,
                snapshot_data={"bids": bids, "asks": asks},
                trade_id=trade_id,
                tenant_id=self.tenant_id,
            )
        except Exception as e:
            logger.debug("Order book snapshot failed (non-fatal)", trade_id=trade_id, error=repr(e))

        # ------------------------------------------------------------------
        # Step 2: ML features — override OBI/spread with entry-time values,
        #         validate all 12 keys are present
        # ------------------------------------------------------------------
        try:
            features = getattr(signal, "prediction_features", None)
            if isinstance(features, dict) and features:
                # Override with entry-time order book values
                if entry_obi is not None and math.isfinite(entry_obi):
                    features["obi"] = entry_obi
                if entry_spread is not None and math.isfinite(entry_spread):
                    features["spread_pct"] = entry_spread

                safe_features: Dict[str, float] = {}
                bad = 0
                for k, v in features.items():
                    if v is None:
                        bad += 1
                        continue
                    try:
                        fv = float(v)
                        if not math.isfinite(fv):
                            bad += 1
                            continue
                        safe_features[str(k)] = fv
                    except Exception:
                        bad += 1
                        continue

                # Backfill missing feature keys with known defaults
                missing = [k for k in self._ML_FEATURE_DEFAULTS if k not in safe_features]
                if missing:
                    logger.info(
                        "ML features backfilled",
                        trade_id=trade_id,
                        pair=signal.pair,
                        missing=missing,
                    )
                    for k in missing:
                        safe_features[k] = self._ML_FEATURE_DEFAULTS[k]

                if safe_features:
                    await self.db.insert_ml_features(
                        pair=signal.pair,
                        features=safe_features,
                        label=None,
                        trade_id=trade_id,
                        tenant_id=self.tenant_id,
                    )
                else:
                    logger.debug(
                        "ML features skipped (no numeric values)",
                        trade_id=trade_id,
                        pair=signal.pair,
                        bad_values=bad,
                    )
        except Exception as e:
            logger.warning(
                "Failed to record ML features (non-fatal)",
                trade_id=trade_id,
                pair=getattr(signal, "pair", None),
                error=repr(e),
                error_type=type(e).__name__,
            )

    async def _get_recent_trades_count(self, cutoff: str) -> int:
        """Fetch recent trade count with a short in-memory cache."""
        now = time.time()
        if (now - self._recent_trades_cache_at) <= self._recent_trades_cache_ttl_seconds:
            return int(self._recent_trades_cache_value)
        value = int(await self.db.count_trades_since(cutoff, tenant_id=self.tenant_id))
        self._recent_trades_cache_value = value
        self._recent_trades_cache_at = now
        return value

    async def manage_open_positions(self) -> None:
        """
        Update all open positions: check stops, trailing logic.
        
        This should be called on every scan cycle to manage
        existing positions.
        
        # ENHANCEMENT: Added parallel position management
        """
        open_trades = await self.db.get_open_trades(tenant_id=self.tenant_id)

        if open_trades:
            results = await asyncio.gather(
                *[self._manage_position(trade) for trade in open_trades],
                return_exceptions=True,
            )
            for trade, result in zip(open_trades, results):
                if isinstance(result, Exception):
                    logger.error(
                        "Position management error",
                        trade_id=trade["trade_id"],
                        error=str(result),
                    )

    async def _place_exchange_stop(
        self, trade_id: str, pair: str, side: str, stop_price: float, volume: float
    ) -> Optional[str]:
        """Place a stop-loss order on the exchange as a crash-proof safety net.

        The software trailing stops remain primary. This exchange stop is placed
        at the initial SL level and updated when the trailing stop moves.
        """
        if not self.rest_client:
            return None
        try:
            # Stop-loss sell for longs, stop-loss buy for shorts
            stop_side = "sell" if side == "buy" else "buy"
            coid = f"{trade_id}-sl"
            result = await self.rest_client.place_order(
                pair=pair,
                side=stop_side,
                order_type="stop-loss",
                volume=volume,
                price=stop_price,
                client_order_id=coid,
                reduce_only=True,
            )
            txid = None
            if "txid" in result:
                txid = result["txid"][0] if isinstance(result["txid"], list) else result["txid"]
            if txid:
                # Store the stop order txid in trade metadata for later amendment/cancel
                try:
                    trade = await self.db.get_trade_by_id(trade_id, tenant_id=self.tenant_id)
                    if trade:
                        meta = self._parse_meta(trade.get("metadata"))
                        meta["exchange_stop_txid"] = txid
                        await self.db.update_trade(trade_id, {"metadata": meta}, tenant_id=self.tenant_id)
                except Exception as e:
                    logger.warning("Failed to persist exchange stop txid", trade_id=trade_id, error=repr(e))
                logger.info("Exchange stop order placed", trade_id=trade_id, pair=pair, stop_price=stop_price, txid=txid)
            return txid
        except Exception as e:
            # Non-fatal: software stops still protect the position
            logger.warning("Exchange stop order failed (software stop still active)", trade_id=trade_id, error=repr(e))
            return None

    async def _update_exchange_stop(
        self, trade_id: str, pair: str, side: str, new_stop_price: float, volume: float
    ) -> None:
        """Cancel existing exchange stop and place a new one at updated price."""
        if not self.rest_client:
            return
        try:
            # Get current stop txid from metadata
            trade = await self.db.get_trade_by_id(trade_id, tenant_id=self.tenant_id)
            if not trade:
                return
            meta = self._parse_meta(trade.get("metadata"))
            old_txid = meta.get("exchange_stop_txid")
            if old_txid:
                try:
                    await self.rest_client.cancel_order(old_txid)
                except Exception:
                    pass  # May already be filled/cancelled

            # Place new stop at updated price
            new_txid = await self._place_exchange_stop(trade_id, pair, side, new_stop_price, volume)
            if new_txid is None and old_txid:
                # Cancel succeeded but new placement failed — no exchange stop active.
                # Flag this trade for software-only stop management.
                logger.critical(
                    "Exchange stop gap: cancel succeeded but replacement failed",
                    trade_id=trade_id, pair=pair,
                )
                try:
                    meta["software_stop_only"] = True
                    meta.pop("exchange_stop_txid", None)
                    await self.db.update_trade(trade_id, {"metadata": meta}, tenant_id=self.tenant_id)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Exchange stop update failed (software stop still active)", trade_id=trade_id, error=repr(e))

    async def _cancel_exchange_stop(self, trade_id: str) -> None:
        """Cancel any exchange-native stop order for this trade."""
        if not self.rest_client:
            return
        try:
            trade = await self.db.get_trade_by_id(trade_id, tenant_id=self.tenant_id)
            if not trade:
                return
            meta = self._parse_meta(trade.get("metadata"))
            txid = meta.get("exchange_stop_txid")
            if txid:
                try:
                    await self.rest_client.cancel_order(txid)
                    logger.info("Exchange stop cancelled", trade_id=trade_id, txid=txid)
                except Exception:
                    pass  # May already be filled/cancelled
        except Exception as e:
            logger.debug("Exchange stop cancel lookup failed", trade_id=trade_id, error=repr(e))

    async def _manage_position(self, trade: Dict[str, Any]) -> None:
        """Manage a single open position (with per-trade lock)."""
        trade_id = trade["trade_id"]
        lock = self._position_locks.setdefault(trade_id, asyncio.Lock())
        async with lock:
            await self._manage_position_inner(trade)
        # Clean up lock if position no longer open in risk manager
        if trade_id not in self.risk_manager._open_positions:
            self._position_locks.pop(trade_id, None)

    async def _manage_position_inner(self, trade: Dict[str, Any]) -> None:
        """Inner position management logic (called under per-trade lock)."""
        trade_id = trade["trade_id"]
        pair = trade["pair"]
        side = trade["side"]
        entry_price = trade["entry_price"]
        quantity = trade["quantity"]

        # Skip managing positions with stale data — stale prices from a
        # disconnected WS could trigger false stop-outs or take-profits
        if self.market_data.is_stale(pair, max_age_seconds=120):
            return

        current_price = self.market_data.get_latest_price(pair)
        if current_price <= 0:
            return

        # Compute trade age (used for max-duration check and hold-duration optimization)
        entry_time_str = trade.get("entry_time", "")
        age_hours = 0.0
        if entry_time_str:
            try:
                entry_dt = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
            except Exception:
                pass

        # Max trade duration: auto-close positions older than configured limit
        max_duration_hours = self.max_trade_duration_hours
        if age_hours >= max_duration_hours and entry_time_str:
            await self._close_position(
                trade_id, pair, side, entry_price,
                current_price, quantity, "max_duration",
                metadata=trade.get("metadata"),
                strategy=trade.get("strategy"),
            )
            return

        # Update trailing stop (pass vol_regime from trade metadata for regime-aware stops)
        meta = self._parse_meta(trade.get("metadata"))
        vol_regime = meta.get("vol_regime", "") if meta else ""
        state = self.risk_manager.update_stop_loss(
            trade_id, current_price, entry_price, side, vol_regime=vol_regime
        )

        # ATR-based stagnation detection: tighten TP when price fails to
        # make expected progress relative to ATR.  Replaces time-only logic.
        take_profit = float(trade.get("take_profit", 0) or 0)
        if take_profit > 0 and entry_price > 0 and age_hours > 0:
            age_minutes = age_hours * 60
            if side == "buy":
                pnl_pct = (current_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_price) / entry_price

            tp_tightened = False

            # Try ATR-based stagnation (preferred method)
            atr_pct = float(meta.get("atr_pct", 0) or 0) if meta else 0
            if atr_pct > 0 and age_minutes > 15:
                import math as _math
                # Expected move scales with sqrt of time (random walk model)
                # bars_held ≈ age_minutes (1-min candles) / atr_period(14)
                bars_held = age_minutes  # 1-min candle count
                expected_move_pct = atr_pct * _math.sqrt(bars_held / 14.0)
                actual_move_pct = abs(pnl_pct)

                # Stagnation ratio: how much of expected move was realized
                stagnation_ratio = actual_move_pct / expected_move_pct if expected_move_pct > 0 else 1.0

                if stagnation_ratio < 0.2 and age_minutes > 45:
                    # Severe stagnation: barely moved despite expected vol → TP to 40%
                    if side == "buy":
                        new_tp = entry_price + (take_profit - entry_price) * 0.4
                    else:
                        new_tp = entry_price - (entry_price - take_profit) * 0.4
                    tp_tightened = True
                elif stagnation_ratio < 0.3 and age_minutes > 30:
                    # Moderate stagnation → TP to 60%
                    if side == "buy":
                        new_tp = entry_price + (take_profit - entry_price) * 0.6
                    else:
                        new_tp = entry_price - (entry_price - take_profit) * 0.6
                    tp_tightened = True
            else:
                # Fallback: time-based tightening when ATR data is unavailable
                if age_minutes > 60 and pnl_pct < 0.01:
                    if side == "buy":
                        new_tp = entry_price + (take_profit - entry_price) * 0.4
                    else:
                        new_tp = entry_price - (entry_price - take_profit) * 0.4
                    tp_tightened = True
                elif age_minutes > 30 and pnl_pct < 0.005:
                    if side == "buy":
                        new_tp = entry_price + (take_profit - entry_price) * 0.6
                    else:
                        new_tp = entry_price - (entry_price - take_profit) * 0.6
                    tp_tightened = True

            if tp_tightened:
                await self.db.update_trade(trade_id, {
                    "take_profit": new_tp,
                }, tenant_id=self.tenant_id)
                # Use tightened TP for the rest of this cycle
                trade["take_profit"] = new_tp

        # Hold-duration optimization: if the trade has been open longer than
        # 2x the strategy's average winning hold time, tighten the trailing
        # stop to lock in any remaining profit (prevent "hope trades").
        strategy_name = trade.get("strategy", "")
        if strategy_name and self._confluence and entry_time_str and state.current_sl > 0:
            try:
                avg_win_hours = self._confluence.avg_winning_hold_hours(strategy_name)
                if avg_win_hours > 0 and age_hours > 2 * avg_win_hours:
                    # Trade is overstaying — tighten SL to 50% of current distance
                    if side == "buy":
                        distance = current_price - state.current_sl
                        if distance > 0:
                            tightened = current_price - distance * 0.5
                            if tightened > state.current_sl:
                                state.current_sl = tightened
                    else:
                        distance = state.current_sl - current_price
                        if distance > 0:
                            tightened = current_price + distance * 0.5
                            if tightened < state.current_sl:
                                state.current_sl = tightened
            except Exception:
                pass  # Non-fatal: default trailing stop still protects

        # Check if stopped out
        if self.risk_manager.should_stop_out(trade_id, current_price, side):
            await self._close_position(
                trade_id, pair, side, entry_price,
                current_price, quantity, "stop_loss",
                metadata=trade.get("metadata"),
                strategy=trade.get("strategy"),
            )
            return

        # Smart exit: partial closes at tiered TP levels
        if self._is_smart_exit_enabled():
            partial_closed = await self._check_smart_exit(trade, current_price)
            if partial_closed:
                return  # Tier triggered, position updated — skip flat TP check

        # Check take profit
        take_profit = trade.get("take_profit", 0)
        if take_profit > 0:
            tp_hit = (side == "buy" and current_price >= take_profit) or \
                     (side == "sell" and current_price <= take_profit)
            if tp_hit:
                await self._close_position(
                    trade_id, pair, side, entry_price,
                    current_price, quantity, "take_profit",
                    metadata=trade.get("metadata"),
                    strategy=trade.get("strategy"),
                )
                return

        # Update stop loss in DB if changed
        if state.current_sl > 0:
            # Prepare metadata update with stop loss state
            meta = self._parse_meta(trade.get("metadata"))
            had_stop_loss_state = isinstance(meta.get("stop_loss_state"), dict)
            
            meta["stop_loss_state"] = state.to_dict()
            
            # Only update if SL changed or we just need to persist state
            prior_sl = float(trade.get("stop_loss", 0) or 0)
            if abs(float(state.current_sl) - prior_sl) > 1e-10 or not had_stop_loss_state:
                await self.db.update_trade(trade_id, {
                    "stop_loss": state.current_sl,
                    "trailing_stop": state.current_sl if state.trailing_activated else None,
                    "metadata": meta
                }, tenant_id=self.tenant_id)

                # Update exchange stop order if SL moved significantly
                sl_moved_significantly = (
                    prior_sl > 0
                    and abs(float(state.current_sl) - prior_sl) / prior_sl > 0.005
                )
                if self.mode == "live" and sl_moved_significantly:
                    await self._update_exchange_stop(trade_id, trade["pair"], side, state.current_sl, quantity)

    async def _exit_live_order(
        self,
        trade_id: str,
        pair: str,
        side: str,
        quantity: float,
        tenant_id: str,
    ) -> Optional[tuple]:
        """Place a live market exit order with typed retry logic.

        Returns (exit_price, filled_quantity, exit_fee) on success,
        or None if the exit fails permanently (trade is marked as error).
        """
        close_side = "sell" if side == "buy" else "buy"
        actual_exit_price = 0.0
        actual_quantity = quantity
        exit_fee = 0.0

        for attempt in range(3):
            try:
                place_sig = inspect.signature(self.rest_client.place_order)
                extra_kwargs = {}
                if "reduce_only" in place_sig.parameters:
                    extra_kwargs["reduce_only"] = True
                result = await self.rest_client.place_order(
                    pair=pair,
                    side=close_side,
                    order_type="market",
                    volume=quantity,
                    **extra_kwargs,
                )
                txid = None
                if isinstance(result, dict):
                    txids = result.get("txid") or []
                    if isinstance(txids, list) and txids:
                        txid = txids[0]
                    elif isinstance(txids, str):
                        txid = txids
                if txid:
                    fill_price, filled_units, partial, fee = await self._wait_for_fill(
                        txid, timeout=30
                    )
                    if fill_price and filled_units and filled_units > 0:
                        actual_exit_price = fill_price
                        if filled_units < actual_quantity:
                            logger.warning(
                                "Partial exit fill detected",
                                trade_id=trade_id,
                                requested=actual_quantity,
                                filled=filled_units,
                            )
                            actual_quantity = filled_units
                        exit_fee = fee if fee and fee > 0 else 0.0
                return (actual_exit_price, actual_quantity, exit_fee)
            except PermanentExchangeError as e:
                logger.error(
                    "Exit order permanently failed (non-retryable)",
                    trade_id=trade_id, attempt=attempt + 1,
                    error=str(e), error_type=type(e).__name__,
                )
                break  # No retry for permanent errors
            except RateLimitError as e:
                delay = max(e.retry_after, 2 ** attempt)
                logger.warning(
                    "Exit order rate-limited, backing off",
                    trade_id=trade_id, attempt=attempt + 1,
                    error=str(e), delay=delay,
                )
                if attempt < 2:
                    await asyncio.sleep(delay)
                    continue
                break
            except TransientExchangeError as e:
                logger.warning(
                    "Exit order failed (transient), retrying",
                    trade_id=trade_id, attempt=attempt + 1,
                    error=str(e), error_type=type(e).__name__,
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                break
            except Exception as e:
                logger.error(
                    "Exit order failed",
                    trade_id=trade_id, attempt=attempt + 1, error=str(e),
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                break

        # All retries exhausted — mark trade as error
        await self.db.update_trade(trade_id, {
            "notes": "EXIT FAILED after 3 attempts",
            "status": "error",
        }, tenant_id=tenant_id)
        logger.critical("Exit order permanently failed", trade_id=trade_id)
        self.risk_manager.close_position(trade_id, 0.0)
        return None

    async def _close_position(
        self,
        trade_id: str,
        pair: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        strategy: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Close a position and record the result.
        Optional tenant_id for multi-tenant close_all; defaults to self.tenant_id."""
        # Cancel exchange stop order if present
        if self.mode == "live" and self.rest_client:
            await self._cancel_exchange_stop(trade_id)

        tid = tenant_id if tenant_id is not None else self.tenant_id
        # C7 FIX: Include both entry and exit fees in PnL
        entry_fee_rate = self.taker_fee
        meta = self._parse_meta(metadata)

        if meta:
            meta_entry_fee = float(meta.get("entry_fee", 0.0) or 0.0)
            if meta_entry_fee > 0 and entry_price * quantity > 0:
                entry_fee_rate = meta_entry_fee / (entry_price * quantity)
            else:
                entry_fee_rate = float(meta.get("entry_fee_rate", self.taker_fee) or self.taker_fee)

        actual_exit_price = exit_price
        actual_quantity = quantity
        exit_fee = 0.0

        # C6 FIX: Retry exit order in live mode; don't leave ghost positions
        if self.mode == "live":
            result = await self._exit_live_order(
                trade_id, pair, side, quantity, tid,
            )
            if result is None:
                return  # Exit failed permanently — already logged and marked error
            actual_exit_price, actual_quantity, exit_fee = result

        if actual_quantity <= 0 and self.mode == "live":
            # In live mode, zero fill means the order genuinely failed.
            # In paper mode or smart_exit_final, quantity may be 0 because
            # partial exits already closed the position — still record PnL.
            return

        if actual_quantity != quantity and actual_quantity > 0:
            try:
                await self.db.update_trade(trade_id, {
                    "quantity": actual_quantity,
                    "notes": f"Partial exit fill: {actual_quantity:.8f}/{quantity:.8f}",
                }, tenant_id=tid)
            except Exception as e:
                logger.warning(
                    "Failed to update partial fill quantity in DB",
                    trade_id=trade_id, error=repr(e),
                )

        # Use stored entry_fee from trade metadata when available (avoids
        # recalculating with a potentially different rate after partial fills).
        stored_entry_fee = float(meta.get("entry_fee", 0.0) or 0.0) if meta else 0.0
        if stored_entry_fee > 0 and actual_quantity > 0 and quantity > 0:
            # Scale stored fee proportionally if this is a partial close
            entry_fee = stored_entry_fee * (actual_quantity / quantity)
        else:
            entry_fee = abs(entry_price * actual_quantity) * entry_fee_rate
        if exit_fee <= 0:
            exit_fee = abs(actual_exit_price * actual_quantity) * self.taker_fee
        fees = entry_fee + exit_fee

        if side == "buy":
            pnl = (actual_exit_price - entry_price) * actual_quantity
        else:
            pnl = (entry_price - actual_exit_price) * actual_quantity

        pnl -= fees  # Net P&L after ALL fees

        # Add accumulated partial P&L from smart exit tiers
        partial_pnl = float(meta.get("partial_pnl_accumulated", 0.0) or 0.0)
        pnl += partial_pnl

        # M28 FIX: Calculate pnl_pct AFTER fee deduction
        pnl_pct = pnl / (entry_price * actual_quantity) if entry_price * actual_quantity > 0 else 0

        # Update database
        await self.db.close_trade(
            trade_id, actual_exit_price, pnl, pnl_pct, fees,
            tenant_id=tid,
        )
        self._enqueue_trade_event(
            "closed",
            {
                "trade_id": trade_id,
                "tenant_id": tid,
                "pair": pair,
                "side": side,
                "mode": self.mode,
                "status": "closed",
                "entry_price": entry_price,
                "exit_price": actual_exit_price,
                "quantity": actual_quantity,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": reason,
                "fees": fees,
            },
        )
        # Label the ML row for this trade (1=win, 0=loss/breakeven).
        ml_label = 1.0 if pnl > 0 else 0.0
        try:
            await self.db.update_ml_label_for_trade(
                trade_id,
                ml_label,
                tenant_id=tid,
            )
        except Exception as e:
            logger.debug("ML label update failed (non-fatal)", trade_id=trade_id, error=repr(e))

        # Record strategy attribution
        try:
            entry_time = None
            strategy_name = strategy or ""
            conf_count = 0
            confidence_val = 0.0
            regime_val = None
            vol_regime_val = None
            if meta:
                entry_time = meta.get("entry_time")
                conf_count = int(meta.get("confluence_count", 0) or 0)
                confidence_val = float(meta.get("confidence", 0.0) or 0.0)
                regime_val = meta.get("regime")
                vol_regime_val = meta.get("volatility_regime")
            exit_time_str = datetime.now(timezone.utc).isoformat()
            duration = 0.0
            if entry_time:
                try:
                    entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
                    duration = (datetime.now(timezone.utc) - entry_dt).total_seconds()
                except Exception:
                    pass
            session_hour = datetime.now(timezone.utc).hour
            await self.db.insert_attribution({
                "trade_id": trade_id,
                "strategy": strategy_name,
                "regime": regime_val,
                "volatility_regime": vol_regime_val,
                "pair": pair,
                "direction": side,
                "pnl": round(pnl, 6),
                "pnl_pct": round(pnl_pct, 6),
                "entry_time": entry_time,
                "exit_time": exit_time_str,
                "duration_seconds": duration,
                "session_hour": session_hour,
                "confluence_count": conf_count,
                "confidence": confidence_val,
            }, tenant_id=tid)
        except Exception as e:
            logger.warning("Attribution record failed", trade_id=trade_id, error=repr(e))

        # Feed the closed trade to the continuous learner for online ML updates.
        if self.continuous_learner:
            try:
                features = await self.db.get_ml_features_for_trade(trade_id, tenant_id=tid)
                if features:
                    await self.continuous_learner.update(features, ml_label)
                    logger.info(
                        "Continuous learner updated",
                        trade_id=trade_id,
                        label=ml_label,
                        updates=self.continuous_learner.stats.updates,
                    )
            except Exception as e:
                logger.debug("Continuous learner update failed (non-fatal)", trade_id=trade_id, error=repr(e))

        # Update risk manager
        self.risk_manager.close_position(trade_id, pnl)
        if self._strategy_result_cb and strategy:
            try:
                trend_regime = meta.get("trend_regime", "") if meta else ""
                vol_regime = meta.get("vol_regime", "") if meta else ""
                hold_hours = 0.0
                # Use canonical entry_time from trade record, not metadata
                _trade_row = await self.db.get_trade_by_id(trade_id, tenant_id=tid)
                _et = (_trade_row or {}).get("entry_time", "") or (meta.get("entry_time", "") if meta else "")
                if _et:
                    try:
                        _entry_dt = datetime.fromisoformat(str(_et).replace("Z", "+00:00"))
                        hold_hours = (datetime.now(timezone.utc) - _entry_dt).total_seconds() / 3600.0
                    except Exception:
                        pass
                self._strategy_result_cb(strategy, pnl, trend_regime, vol_regime, hold_hours=hold_hours)
            except Exception as e:
                logger.debug("Strategy result callback failed (non-fatal)", strategy=strategy, error=repr(e))

        # Log thought
        emoji = "✅" if pnl > 0 else "❌"
        await self.db.log_thought(
            "trade",
            f"{emoji} CLOSED {pair} ({reason}) | PnL: ${pnl:.2f} ({pnl_pct:.2%}) | "
            f"Entry: ${entry_price:.2f} -> Exit: ${actual_exit_price:.2f}",
            severity="info" if pnl > 0 else "warning",
            metadata={
                "trade_id": trade_id,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": reason,
                "fees": fees,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
            },
            tenant_id=tid,
        )

        logger.info(
            "Position closed",
            trade_id=trade_id,
            pair=pair,
            pnl=round(pnl, 2),
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Smart Exit (Partial Close Tiers)
    # ------------------------------------------------------------------

    def _is_smart_exit_enabled(self) -> bool:
        """Check and cache smart exit config."""
        if self._smart_exit_enabled is not None:
            return self._smart_exit_enabled
        self._smart_exit_enabled = bool(self._smart_exit_constructor_flag)
        self._smart_exit_tiers = self._smart_exit_constructor_tiers if self._smart_exit_enabled else []
        return self._smart_exit_enabled

    async def _check_smart_exit(self, trade: Dict[str, Any], current_price: float) -> bool:
        """Check if a smart exit tier should trigger. Returns True if a partial close happened.

        Regime-aware: adjusts tier targets based on volatility regime.
        - high_vol: widen targets (1.5x/2.5x) to let winners run in volatile markets
        - low_vol: tighten targets (0.8x/1.2x) to capture profits before reversal
        """
        tiers = self._smart_exit_tiers or []
        if not tiers:
            return False

        meta = self._parse_meta(trade.get("metadata"))

        current_tier = int(meta.get("exit_tier", 0))
        if current_tier >= len(tiers):
            return False  # All tiers exhausted

        tier = tiers[current_tier]
        tp_mult = float(tier.tp_mult) if hasattr(tier, "tp_mult") else float(tier.get("tp_mult", 0))
        tier_pct = float(tier.pct) if hasattr(tier, "pct") else float(tier.get("pct", 0))

        if tp_mult <= 0:
            return False  # This tier = trailing stop only, handled by normal SL logic

        # Regime-aware tier adjustment
        vol_regime = meta.get("vol_regime", "") if meta else ""
        if vol_regime == "high_vol":
            tp_mult *= 1.5   # Wider targets in volatile markets
        elif vol_regime == "low_vol":
            tp_mult *= 0.8   # Tighter targets in calm markets

        entry = trade["entry_price"]
        original_tp = trade.get("take_profit", 0)
        if not original_tp or original_tp <= 0 or entry <= 0:
            return False

        tp_distance = abs(original_tp - entry)
        side = trade["side"]

        if side == "buy":
            tier_target = entry + tp_distance * tp_mult
            triggered = current_price >= tier_target
        else:
            tier_target = entry - tp_distance * tp_mult
            triggered = current_price <= tier_target

        if triggered:
            partial_qty = trade["quantity"] * tier_pct
            if partial_qty <= 0:
                return False
            # If the tier effectively closes the full remaining position,
            # route through the normal close path to avoid zero-quantity remnants.
            if partial_qty >= (trade["quantity"] - 1e-8):
                await self._close_position(
                    trade["trade_id"],
                    trade["pair"],
                    side,
                    entry,
                    current_price,
                    trade["quantity"],
                    f"smart_exit_tier_{current_tier + 1}",
                    metadata=trade.get("metadata"),
                    strategy=trade.get("strategy"),
                )
                return True
            await self._close_partial(trade, current_price, partial_qty, current_tier, meta)
            return True
        return False

    async def _close_partial(
        self,
        trade: Dict[str, Any],
        exit_price: float,
        partial_qty: float,
        tier_idx: int,
        meta: Dict[str, Any],
    ) -> None:
        """Close a partial position at a smart exit tier."""
        trade_id = trade["trade_id"]
        side = trade["side"]
        entry_price = trade["entry_price"]
        quantity = trade["quantity"]

        # Compute partial P&L
        if side == "buy":
            partial_pnl = (exit_price - entry_price) * partial_qty
        else:
            partial_pnl = (entry_price - exit_price) * partial_qty

        # Subtract fees for this partial close
        fee = abs(exit_price * partial_qty) * self.taker_fee
        partial_pnl -= fee

        # Update metadata
        partial_exits = meta.get("partial_exits", [])
        partial_exits.append({
            "tier": tier_idx,
            "qty": round(partial_qty, 8),
            "price": round(exit_price, 2),
            "pnl": round(partial_pnl, 4),
            "fee": round(fee, 4),
            "time": datetime.now(timezone.utc).isoformat(),
        })
        meta["partial_exits"] = partial_exits
        meta["exit_tier"] = tier_idx + 1
        accumulated = float(meta.get("partial_pnl_accumulated", 0.0))
        meta["partial_pnl_accumulated"] = round(accumulated + partial_pnl, 4)

        # Update remaining quantity
        remaining = max(0.0, quantity - partial_qty)

        # Persist to DB
        await self.db.update_trade(trade_id, {
            "quantity": remaining,
            "metadata": meta,
        }, tenant_id=self.tenant_id)

        # Reduce risk manager exposure
        reduction_fraction = (partial_qty / quantity) if quantity > 0 else 0.0
        self.risk_manager.reduce_position_size(
            trade_id,
            reduction_fraction=reduction_fraction,
        )

        # If position is fully closed, finalize via close_position with the
        # original partial_qty (not 0) so PnL is recorded correctly.
        if remaining < 1e-8:
            await self._close_position(
                trade_id,
                trade["pair"],
                side,
                entry_price,
                exit_price,
                partial_qty,
                "smart_exit_final",
                metadata=meta,
                strategy=trade.get("strategy"),
            )
            return

        # Log the partial exit
        await self.db.log_thought(
            "trade",
            f"📊 PARTIAL EXIT tier {tier_idx + 1} | {trade['pair']} | "
            f"Closed {partial_qty:.6f} @ ${exit_price:.2f} | "
            f"PnL: ${partial_pnl:.2f} | Remaining: {remaining:.6f}",
            severity="info",
            metadata={
                "trade_id": trade_id,
                "tier": tier_idx,
                "partial_pnl": partial_pnl,
                "remaining_qty": remaining,
            },
            tenant_id=self.tenant_id,
        )

        logger.info(
            "Smart exit partial close",
            trade_id=trade_id,
            tier=tier_idx + 1,
            partial_qty=round(partial_qty, 8),
            exit_price=round(exit_price, 2),
            partial_pnl=round(partial_pnl, 4),
            remaining=round(remaining, 8),
        )

    def _enqueue_trade_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Mirror trade lifecycle events to Elasticsearch (best-effort)."""
        if not self.es_client:
            return
        now = time.time()
        doc: Dict[str, Any] = {
            "event": event,
            "timestamp": int(now),
            **payload,
        }
        # Persistence contract: SQLite is the canonical ledger; ES is mirror-only.
        doc["canonical_source"] = "sqlite"
        doc["analytics_mirror"] = True
        trade_id = str(payload.get("trade_id", "") or "")
        doc_id = f"{trade_id}:{event}:{int(now)}" if trade_id else None
        try:
            self.es_client.enqueue("trades", doc, doc_id=doc_id, timestamp=now)
        except Exception as e:
            logger.debug("Trade event ES enqueue failed", event=event, error=repr(e))

    # ------------------------------------------------------------------
    # Fill Processing
    # ------------------------------------------------------------------

    async def _paper_fill(
        self, pair: str, side: str, target_price: float
    ) -> Optional[float]:
        """
        Simulate a fill in paper trading mode.
        
        Applies realistic slippage based on spread and volatility.
        
        # ENHANCEMENT: Added volume-aware slippage model
        # ENHANCEMENT: Limit order simulation
        """
        spread = self.market_data.get_spread(pair)

        # Realistic slippage model: 70% adverse, 20% neutral, 10% favorable.
        # Magnitude is spread-based with randomness.
        base_slip = max(spread / 10, 0.00005)
        roll = random.random()
        if roll < 0.10:
            # Favorable: fill slightly better than target
            slippage_pct = -base_slip * random.uniform(0.2, 0.8)
        elif roll < 0.30:
            # Neutral: fill at or very near target
            slippage_pct = base_slip * random.uniform(-0.1, 0.1)
        else:
            # Adverse: fill slightly worse than target
            slippage_pct = base_slip * random.uniform(0.3, 1.5)

        if side == "buy":
            fill_price = target_price * (1 + slippage_pct)
        else:
            fill_price = target_price * (1 - slippage_pct)

        return round(fill_price, 8)

    async def _live_fill(
        self,
        pair: str,
        side: str,
        order_type: str,
        volume: float,
        client_order_id: str,
        price: Optional[float] = None,
        post_only: bool = False,
    ) -> tuple[Optional[float], Optional[float], bool, float]:
        """
        Execute a live order on Kraken.
        
        # ENHANCEMENT: Added order monitoring with timeout
        # ENHANCEMENT: Support for Limit orders
        """
        # Enforce exchange precision and minimum size
        price_decimals = None
        try:
            min_size = await self.rest_client.get_min_order_size(pair)
            price_decimals, lot_decimals = await self.rest_client.get_pair_decimals(pair)
            if volume < min_size:
                logger.warning(
                    "Order volume below minimum size",
                    pair=pair, volume=volume, min_size=min_size
                )
                return None, None, False, 0.0
            volume = round(float(volume), int(lot_decimals))
            if price is not None and price_decimals is not None:
                price = round(float(price), int(price_decimals))
        except Exception as e:
            logger.warning(
                "Failed to normalize order size/price",
                pair=pair, error=str(e)
            )

        def _best_limit_price() -> Optional[float]:
            ticker = self.market_data.get_ticker(pair)
            if ticker:
                try:
                    if side == "buy":
                        return float(ticker["a"][0])
                    return float(ticker["b"][0])
                except Exception:
                    return None
            return None

        try:
            attempts = self.limit_chase_attempts if order_type == "limit" else 0
            chase_timeout = 10

            for attempt in range(attempts + 1):
                coid = client_order_id
                if client_order_id and attempt > 0:
                    coid = f"{client_order_id}-r{attempt}"

                result = await self.rest_client.place_order(
                    pair=pair,
                    side=side,
                    order_type=order_type,
                    volume=volume,
                    price=price,
                    client_order_id=coid,
                    post_only=post_only,
                    validate_only=(self.mode != "live"),
                )

                if result.get("status") == "duplicate":
                    return None, None, False, 0.0

                txid = None
                if "txid" in result:
                    txid = result["txid"][0] if isinstance(result["txid"], list) else result["txid"]
                if txid:
                    fill_price, filled_volume, partial, fee = await self._wait_for_fill(
                        txid, timeout=chase_timeout
                    )
                    if fill_price and filled_volume and filled_volume > 0:
                        return fill_price, filled_volume, partial, fee

                    # Limit chase: cancel and reprice
                    if order_type == "limit" and attempt < attempts:
                        try:
                            await self.rest_client.cancel_order(txid)
                        except Exception:
                            pass
                        if self.limit_chase_delay_seconds > 0:
                            await asyncio.sleep(self.limit_chase_delay_seconds)
                        new_price = _best_limit_price()
                        if new_price:
                            price = round(float(new_price), int(price_decimals)) if price_decimals is not None else new_price
                        continue

            # Fallback to market if limit couldn't fill and not post-only
            if order_type == "limit" and self.limit_fallback_to_market and not post_only:
                fallback_coid = client_order_id
                if client_order_id:
                    fallback_coid = f"{client_order_id}-m"
                result = await self.rest_client.place_order(
                    pair=pair,
                    side=side,
                    order_type="market",
                    volume=volume,
                    client_order_id=fallback_coid,
                    post_only=False,
                    validate_only=(self.mode != "live"),
                )
                txid = None
                if "txid" in result:
                    txid = result["txid"][0] if isinstance(result["txid"], list) else result["txid"]
                if txid:
                    return await self._wait_for_fill(txid, timeout=30)

            return None, None, False, 0.0

        except PermanentExchangeError as e:
            logger.warning(
                "Live order permanently failed",
                pair=pair, side=side, error=str(e),
                error_type=type(e).__name__,
            )
            return None, None, False, 0.0
        except TransientExchangeError as e:
            logger.debug(
                "Live order failed (transient)",
                pair=pair, side=side, error=str(e),
                error_type=type(e).__name__,
            )
            return None, None, False, 0.0
        except Exception as e:
            logger.error(
                "Live order failed",
                pair=pair, side=side, error=str(e)
            )
            return None, None, False, 0.0

    def _coerce_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _extract_order_fill(
        self, order_info: Dict[str, Any]
    ) -> tuple[float, float, float, float]:
        vol_exec = self._coerce_float(order_info.get("vol_exec", 0))
        vol_total = self._coerce_float(order_info.get("vol", 0))
        cost = self._coerce_float(order_info.get("cost", 0))
        fee = self._coerce_float(order_info.get("fee", 0))
        price = self._coerce_float(order_info.get("price", 0))
        avg_price = self._coerce_float(order_info.get("avg_price", 0))

        if price <= 0:
            price = avg_price
        if price <= 0 and isinstance(order_info.get("descr"), dict):
            price = self._coerce_float(order_info["descr"].get("price", 0))
        if price <= 0 and cost > 0 and vol_exec > 0:
            price = cost / vol_exec
        if cost <= 0 and price > 0 and vol_exec > 0:
            cost = price * vol_exec

        return price, vol_exec, vol_total, fee

    async def _fill_from_trade_history(
        self, txid: str, lookback_seconds: int = 7200
    ) -> tuple[float, float, float]:
        """
        Compute average fill price/volume/fee from trade history for an order.
        Kraken sometimes reports vol_exec without cost/price on open orders.
        """
        try:
            end_ts = int(time.time())
            start_ts = max(0, end_ts - lookback_seconds)
            history = await self.rest_client.get_trades_history(
                start=start_ts, end=end_ts
            )
            trades = history.get("trades") or {}
            total_vol = 0.0
            total_cost = 0.0
            total_fee = 0.0
            for trade in trades.values():
                order_txid = trade.get("ordertxid") or trade.get("order_txid")
                if order_txid != txid:
                    continue
                vol = self._coerce_float(trade.get("vol", 0))
                price = self._coerce_float(trade.get("price", 0))
                fee = self._coerce_float(trade.get("fee", 0))
                if vol <= 0 or price <= 0:
                    continue
                total_vol += vol
                total_cost += price * vol
                total_fee += fee
            if total_vol > 0:
                return total_cost / total_vol, total_vol, total_fee
        except Exception:
            pass
        return 0.0, 0.0, 0.0

    async def _resolve_fill_data(
        self,
        txid: str,
        price: float,
        vol_exec: float,
        fee: float,
        prefer_fee: bool = False,
    ) -> tuple[float, float, float]:
        if vol_exec <= 0:
            return price, vol_exec, fee
        if price > 0 and fee > 0 and not prefer_fee:
            return price, vol_exec, fee
        th_price, th_vol, th_fee = await self._fill_from_trade_history(txid)
        if th_price > 0:
            price = th_price
        if th_vol > 0:
            vol_exec = th_vol
        if th_fee > 0:
            fee = th_fee
        return price, vol_exec, fee

    async def _wait_for_fill(
        self, txid: str, timeout: int = 30
    ) -> tuple[Optional[float], Optional[float], bool, float]:
        """Wait for an order to be filled. Returns (price, filled_volume, partial, fee)."""
        start = time.time()
        last_partial: Optional[tuple[float, float, float]] = None

        while time.time() - start < timeout:
            try:
                orders = await self.rest_client.get_open_orders()
                open_order = orders.get("open", {}).get(txid)
                if open_order:
                    price, vol_exec, vol_total, fee = self._extract_order_fill(open_order)
                    if vol_exec > 0:
                        if price <= 0:
                            try:
                                order_info = await self.rest_client.get_order_info(txid)
                                query = order_info.get(txid)
                                if query:
                                    price, vol_exec, vol_total, fee = self._extract_order_fill(query)
                            except Exception:
                                pass
                        price, vol_exec, fee = await self._resolve_fill_data(
                            txid, price, vol_exec, fee
                        )
                        if price > 0:
                            last_partial = (price, vol_exec, fee)
                        if price > 0 and vol_total > 0 and (vol_exec / vol_total) >= 0.95:
                            return price, vol_exec, True, fee
                    await asyncio.sleep(1)
                    continue

                # Order is no longer open - check closed
                closed = await self.rest_client.get_closed_orders()
                order_info = closed.get("closed", {}).get(txid, {})
                if order_info:
                    price, vol_exec, _vol_total, fee = self._extract_order_fill(order_info)
                    if price <= 0:
                        try:
                            order_query = await self.rest_client.get_order_info(txid)
                            query = order_query.get(txid)
                            if query:
                                price, vol_exec, _vol_total, fee = self._extract_order_fill(query)
                        except Exception:
                            pass
                    price, vol_exec, fee = await self._resolve_fill_data(
                        txid, price, vol_exec, fee, prefer_fee=True
                    )
                    return (price if price > 0 else None, vol_exec, False, fee)
            except Exception:
                pass
            await asyncio.sleep(1)

        # Timeout: cancel remainder and check for any partial fill
        try:
            await self.rest_client.cancel_order(txid)
        except Exception:
            pass

        # Check if we got a partial fill before cancellation
        if last_partial:
            price, vol_exec, fee = last_partial
            return price, vol_exec, True, fee

        return None, None, False, 0.0

    async def close_all_positions(
        self, reason: str = "manual", tenant_id: Optional[str] = None
    ) -> int:
        """
        Emergency close all open positions in parallel for speed.
        Optional tenant_id for API-scoped close (e.g. multi-tenant) - defaults to self.tenant_id.
        """
        tid = tenant_id if tenant_id is not None else self.tenant_id
        open_trades = await self.db.get_open_trades(tenant_id=tid)

        async def _close_one(trade: Dict[str, Any]) -> bool:
            try:
                current_price = self.market_data.get_latest_price(trade["pair"])
                if current_price > 0:
                    await self._close_position(
                        trade["trade_id"],
                        trade["pair"],
                        trade["side"],
                        trade["entry_price"],
                        current_price,
                        trade["quantity"],
                        reason,
                        metadata=trade.get("metadata"),
                        strategy=trade.get("strategy"),
                        tenant_id=tid,
                    )
                    return True
            except Exception as e:
                logger.error(
                    "Emergency close failed",
                    trade_id=trade["trade_id"],
                    error=str(e),
                )
            return False

        results = await asyncio.gather(
            *[_close_one(t) for t in open_trades],
            return_exceptions=True,
        )
        closed_count = sum(1 for r in results if r is True)

        logger.warning(
            "Emergency close all completed",
            closed=closed_count,
            total=len(open_trades),
            reason=reason,
        )
        return closed_count

    def _primary_strategy(self, signal: ConfluenceSignal) -> str:
        """Determine the primary strategy from a confluence signal."""
        if not signal.signals:
            return "confluence"
        # Find the strongest agreeing signal
        best = max(
            [s for s in signal.signals if s.direction == signal.direction],
            key=lambda s: s.strength,
            default=None,
        )
        return best.strategy_name if best else "confluence"

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        stats = dict(self._execution_stats)
        stats["mode"] = self.mode
        if stats["orders_filled"] > 0:
            stats["avg_slippage"] = round(
                stats["total_slippage"] / stats["orders_filled"], 6
            )
            stats["avg_fee"] = round(
                stats["total_fees"] / stats["orders_filled"], 4
            )
        return stats
