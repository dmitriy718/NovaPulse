from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.control_router import ControlRouter
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.stocks.alpaca_client import AlpacaClient
from src.stocks.polygon_client import PolygonClient
from src.utils.indicators import ema, rsi

logger = get_logger("stock_swing_engine")

_ALPACA_TERMINAL_REJECT_STATUSES = {
    "canceled",
    "cancelled",
    "expired",
    "rejected",
    "suspended",
    "stopped",
}

_BROKER_RECONCILE_INTERVAL_LOOPS = 4


class _StockMarketDataView:
    """Lightweight market-data adapter for dashboard compatibility."""

    def __init__(self) -> None:
        self._latest: Dict[str, Dict[str, Any]] = {}

    def update(self, symbol: str, *, price: float, bars: int) -> None:
        self._latest[symbol] = {
            "price": float(price),
            "bars": int(bars),
            "updated_at": time.time(),
        }

    def get_latest_price(self, symbol: str) -> float:
        item = self._latest.get(symbol.upper(), {})
        return float(item.get("price", 0.0) or 0.0)

    def get_bar_count(self, symbol: str) -> int:
        item = self._latest.get(symbol.upper(), {})
        return int(item.get("bars", 0) or 0)

    def is_stale(self, symbol: str, max_age_seconds: int = 3600) -> bool:
        item = self._latest.get(symbol.upper())
        if not item:
            return True
        return (time.time() - float(item.get("updated_at", 0) or 0)) > max_age_seconds

    def get_status(self) -> Dict[str, Any]:
        return {
            sym: {
                "price": float(v.get("price", 0.0) or 0.0),
                "bars": int(v.get("bars", 0) or 0),
                "stale": (time.time() - float(v.get("updated_at", 0) or 0)) > 3600,
            }
            for sym, v in self._latest.items()
        }


class _StockRiskAdapter:
    """Minimal risk-report adapter for dashboard aggregation."""

    def __init__(self, initial_bankroll: float) -> None:
        self.initial_bankroll = float(initial_bankroll)
        self.current_bankroll = float(initial_bankroll)
        self._peak_bankroll = float(initial_bankroll)
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._trade_count = 0
        self._wins = 0
        self._losses = 0
        self._total_pnl = 0.0
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        self._daily_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_daily_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._consecutive_wins = 0
            self._consecutive_losses = 0
            self._daily_reset_date = today

    def record_closed_trade(self, pnl: float) -> None:
        self._check_daily_reset()
        self._daily_trades += 1
        self._daily_pnl += float(pnl)
        self._trade_count += 1
        self._total_pnl += float(pnl)
        self.current_bankroll += float(pnl)
        if self.current_bankroll > self._peak_bankroll:
            self._peak_bankroll = self.current_bankroll
        if pnl > 0:
            self._wins += 1
            self._consecutive_wins += 1
            self._consecutive_losses = 0
        elif pnl < 0:
            self._losses += 1
            self._consecutive_losses += 1
            self._consecutive_wins = 0
        else:
            self._losses += 1

    def bootstrap_from_performance(self, perf: Dict[str, Any]) -> None:
        """Restore core counters from persisted DB stats at startup."""
        total_pnl = float(perf.get("total_pnl", 0.0) or 0.0)
        total_trades = int(perf.get("total_trades", 0) or 0)
        wins = int(perf.get("winning_trades", 0) or 0)
        losses = int(perf.get("losing_trades", max(total_trades - wins, 0)) or 0)
        self._trade_count = max(total_trades, 0)
        self._wins = max(wins, 0)
        self._losses = max(losses, 0)
        self._total_pnl = total_pnl
        self.current_bankroll = self.initial_bankroll + total_pnl
        self._peak_bankroll = max(self.initial_bankroll, self.current_bankroll)

    @property
    def win_rate(self) -> float:
        if self._trade_count <= 0:
            return 0.0
        return self._wins / float(self._trade_count)

    @property
    def avg_pnl(self) -> float:
        if self._trade_count <= 0:
            return 0.0
        return self._total_pnl / float(self._trade_count)

    def get_risk_report(self, open_positions: int = 0) -> Dict[str, Any]:
        self._check_daily_reset()
        peak = max(self._peak_bankroll, 1e-9)
        drawdown = max(0.0, (peak - self.current_bankroll) / peak * 100.0)
        return {
            "bankroll": round(self.current_bankroll, 2),
            "initial_bankroll": round(self.initial_bankroll, 2),
            "total_return_pct": round(
                ((self.current_bankroll - self.initial_bankroll) / self.initial_bankroll * 100.0)
                if self.initial_bankroll > 0
                else 0.0,
                2,
            ),
            "peak_bankroll": round(self._peak_bankroll, 2),
            "current_drawdown": round(drawdown, 2),
            "max_drawdown_pct": round(drawdown, 2),
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_trades": int(self._daily_trades),
            "open_positions": int(open_positions),
            "total_exposure_usd": 0.0,
            "risk_of_ruin": 0.0,
            "drawdown_factor": 1.0,
            "remaining_capacity_usd": 0.0,
            "trade_count": int(self._trade_count),
            "consecutive_wins": int(self._consecutive_wins),
            "consecutive_losses": int(self._consecutive_losses),
        }


class _StockExecutorAdapter:
    def __init__(self, engine: "StockSwingEngine") -> None:
        self._engine = engine

    async def close_all_positions(self, reason: str = "control", tenant_id: Optional[str] = None) -> int:
        tid = tenant_id if tenant_id is not None else self._engine.tenant_id
        rows = await self._engine.db.get_open_trades(tenant_id=tid)
        closed = 0
        for trade in rows:
            ok = await self._engine._close_trade(
                trade,
                reason=reason,
                force=True,
            )
            if ok:
                closed += 1
        return closed

    def get_execution_stats(self) -> Dict[str, Any]:
        stats = dict(self._engine._execution_stats)
        stats["orders_pending"] = len(self._engine._pending_opens)
        stats["mode"] = self._engine.mode
        return stats


class StockSwingEngine:
    """
    Daily swing-trading engine for stocks.

    - Market data: Polygon aggregates
    - Execution: Alpaca orders (or paper simulation)
    - Hold policy: min 1 day, max 7 days (configurable)
    """

    def __init__(self, config_override: Optional[Any] = None):
        from src.core.config import get_config

        self.config = config_override or get_config()
        self.mode = self.config.app.mode
        self.exchange_name = "stocks"
        self.tenant_id = self.config.billing.tenant.default_tenant_id
        self.pairs = [s.upper() for s in (self.config.stocks.symbols or [])]
        self.scan_interval = max(60, int(self.config.stocks.scan_interval_seconds))
        self.min_hold_seconds = max(86400, int(self.config.stocks.min_hold_days) * 86400)
        self.max_hold_seconds = max(self.min_hold_seconds, int(self.config.stocks.max_hold_days) * 86400)

        self.db = DatabaseManager(self.config.stocks.db_path)
        self.market_data = _StockMarketDataView()
        self.risk_manager = _StockRiskAdapter(self.config.risk.initial_bankroll)
        self.executor = _StockExecutorAdapter(self)
        self.control_router = ControlRouter(self)
        self.ws_client = type("_NoStockWs", (), {"is_connected": False})()

        self._running = False
        self._trading_paused = False
        self._start_time = 0.0
        self._scan_count = 0
        self._tasks: List[asyncio.Task] = []
        self._auto_pause_reason = ""
        self._pending_opens: Dict[str, Dict[str, Any]] = {}

        self.polygon = PolygonClient(
            api_key=self.config.stocks.polygon_api_key,
            base_url=self.config.stocks.polygon_base_url,
        )
        self.alpaca = AlpacaClient(
            api_key=self.config.stocks.alpaca_api_key,
            api_secret=self.config.stocks.alpaca_api_secret,
            base_url=self.config.stocks.alpaca_base_url,
        )

        self._execution_stats: Dict[str, Any] = {
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
            "orders_closed": 0,
            "orders_pending": 0,
        }

    async def initialize(self) -> None:
        await self.db.initialize()
        await self.polygon.initialize()
        if self.mode == "live":
            await self.alpaca.initialize()
            await self._reconcile_broker_positions(source="startup")
        await self._load_historical_stats()
        await self.db.log_thought(
            "system",
            f"Stock swing engine initialized | symbols={','.join(self.pairs)}",
            severity="info",
            tenant_id=self.tenant_id,
        )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="stocks:scan_loop"),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.alpaca.close()
        await self.polygon.close()
        await self.db.close()

    async def _load_historical_stats(self) -> None:
        """Prime in-memory strategy stats from persisted trade history."""
        try:
            perf = await self.db.get_performance_stats(tenant_id=self.tenant_id)
            self.risk_manager.bootstrap_from_performance(perf)
        except Exception as e:
            logger.warning("Stock stats bootstrap failed", error=repr(e))

    async def _normalize_broker_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch and normalize open broker positions keyed by symbol.

        Returns only long positions with positive quantity because this strategy is long-only.
        """
        if self.mode != "live":
            return {}
        rows = await self.alpaca.list_open_positions()
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                symbol = str(row.get("symbol", "")).upper().strip()
                qty_signed = float(row.get("qty", 0.0) or 0.0)
                qty = abs(qty_signed)
                if not symbol or qty <= 0:
                    continue
                if qty_signed < 0:
                    # Strategy does not support short inventory yet.
                    await self.db.log_thought(
                        "execution",
                        f"Skipping unsupported short broker position {symbol} qty={qty:.4f}",
                        severity="warning",
                        tenant_id=self.tenant_id,
                    )
                    continue
                avg_entry_price = float(row.get("avg_entry_price", 0.0) or 0.0)
                if avg_entry_price <= 0:
                    avg_entry_price = float(row.get("current_price", 0.0) or 0.0)
                if avg_entry_price <= 0:
                    continue
                out[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_entry_price": avg_entry_price,
                    "raw": row,
                }
            except Exception:
                continue
        return out

    async def _materialize_broker_position(
        self,
        symbol: str,
        broker_pos: Dict[str, Any],
        *,
        source: str,
        pending_order_id: str = "",
    ) -> bool:
        """Persist a local open trade from broker truth when local state is missing."""
        order_stub: Dict[str, Any] = {
            "id": pending_order_id or f"reconciled-{symbol.lower()}",
            "status": "filled",
        }
        opened = await self._persist_open_trade(
            symbol=symbol,
            fill_price=float(broker_pos.get("avg_entry_price", 0.0) or 0.0),
            filled_qty=float(broker_pos.get("qty", 0.0) or 0.0),
            order=order_stub,
            count_fill=False,
        )
        if opened:
            await self.db.log_thought(
                "execution",
                (
                    f"Stock OPEN reconciled from broker {symbol} "
                    f"qty={float(broker_pos.get('qty', 0.0) or 0.0):.4f} "
                    f"entry={float(broker_pos.get('avg_entry_price', 0.0) or 0.0):.2f} "
                    f"source={source}"
                ),
                severity="warning",
                tenant_id=self.tenant_id,
            )
        return opened

    async def _reconcile_broker_positions(self, *, source: str) -> None:
        """Ensure local DB has an open row for every live broker position."""
        broker_positions = await self._normalize_broker_positions()
        open_rows = await self.db.get_open_trades(tenant_id=self.tenant_id)
        open_by_symbol = {str(row.get("pair", "")).upper(): row for row in open_rows}

        reconciled = 0
        mismatched = 0
        for symbol, broker_pos in broker_positions.items():
            local = open_by_symbol.get(symbol)
            if local:
                try:
                    local_qty = float(local.get("quantity", 0.0) or 0.0)
                    broker_qty = float(broker_pos.get("qty", 0.0) or 0.0)
                    if abs(local_qty - broker_qty) > 1e-6:
                        mismatched += 1
                        await self.db.log_thought(
                            "execution",
                            (
                                f"Stock startup reconcile qty mismatch {symbol} "
                                f"local={local_qty:.4f} broker={broker_qty:.4f}"
                            ),
                            severity="warning",
                            tenant_id=self.tenant_id,
                        )
                except Exception:
                    pass
                continue

            if await self._materialize_broker_position(symbol, broker_pos, source=source):
                reconciled += 1

        if reconciled or mismatched:
            await self.db.log_thought(
                "system",
                (
                    f"Stock {source} reconciliation complete "
                    f"| broker_positions={len(broker_positions)} "
                    f"reconciled={reconciled} mismatched={mismatched}"
                ),
                severity="warning" if mismatched else "info",
                tenant_id=self.tenant_id,
            )

    async def _auto_pause(self, reason: str, detail: str = "") -> None:
        if self._trading_paused:
            return
        self._trading_paused = True
        self._auto_pause_reason = reason
        msg = f"Stock engine AUTO-PAUSED: {reason}"
        if detail:
            msg = f"{msg} | {detail}"
        await self.db.log_thought(
            "system",
            msg,
            severity="warning",
            tenant_id=self.tenant_id,
        )

    async def _scan_loop(self) -> None:
        while self._running:
            try:
                if self._trading_paused:
                    await asyncio.sleep(self.scan_interval)
                    continue
                self._scan_count += 1

                await self._reconcile_pending_opens()
                if (
                    self.mode == "live"
                    and self._scan_count % _BROKER_RECONCILE_INTERVAL_LOOPS == 0
                ):
                    await self._reconcile_broker_positions(source="periodic")
                open_rows = await self.db.get_open_trades(tenant_id=self.tenant_id)
                open_by_symbol = {str(row.get("pair", "")).upper(): row for row in open_rows}
                pending_symbols = set(self._pending_opens.keys())
                open_count = len(open_rows) + len(pending_symbols)

                for symbol in self.pairs:
                    bars = await self.polygon.get_daily_bars(
                        symbol,
                        limit=max(60, int(self.config.stocks.lookback_bars)),
                    )
                    if not bars:
                        continue
                    closes = np.array([float(b["close"]) for b in bars], dtype=float)
                    latest_price = float(closes[-1])
                    self.market_data.update(symbol, price=latest_price, bars=len(closes))

                    if symbol in pending_symbols:
                        continue

                    signal = self._analyze_signal(closes)
                    open_trade = open_by_symbol.get(symbol)
                    if open_trade:
                        closed = await self._maybe_close_trade(open_trade, latest_price, signal)
                        if closed:
                            open_by_symbol.pop(symbol, None)
                            open_count = max(0, open_count - 1)
                        continue

                    if signal != "buy":
                        continue
                    if open_count >= int(self.config.stocks.max_open_positions):
                        continue
                    opened = await self._open_trade(symbol, latest_price)
                    if opened:
                        open_count += 1
                        open_by_symbol[symbol] = {"pair": symbol}

                await self._apply_runtime_breakers()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Stock scan loop error", error=repr(e))
                await asyncio.sleep(min(self.scan_interval, 60))

    def _analyze_signal(self, closes: np.ndarray) -> str:
        if len(closes) < 60:
            return "hold"
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        rsi14 = rsi(closes, 14)
        c = float(closes[-1])
        e20 = float(ema20[-1]) if np.isfinite(ema20[-1]) else 0.0
        e50 = float(ema50[-1]) if np.isfinite(ema50[-1]) else 0.0
        rv = float(rsi14[-1]) if np.isfinite(rsi14[-1]) else 50.0
        if e20 <= 0 or e50 <= 0:
            return "hold"
        momentum = (float(closes[-1]) / float(closes[-6]) - 1.0) if len(closes) >= 6 and closes[-6] > 0 else 0.0

        if c > e20 > e50 and 45.0 <= rv <= 72.0 and momentum > 0:
            return "buy"
        if c < e20 or rv >= 78.0 or rv <= 35.0:
            return "exit"
        return "hold"

    async def _open_trade(self, symbol: str, market_price: float) -> bool:
        symbol = str(symbol or "").upper().strip()
        if not symbol:
            return False
        if market_price <= 0:
            return False
        size_usd = float(self.config.stocks.max_position_usd)
        qty = round(size_usd / market_price, 6)
        if qty <= 0:
            return False

        fill_price = market_price
        filled_qty = qty
        self._execution_stats["orders_placed"] += 1

        if self.mode == "live":
            order = await self.alpaca.submit_market_order(symbol=symbol, qty=qty, side="buy")
            if not order:
                self._execution_stats["orders_rejected"] += 1
                return False
            status = str(order.get("status", "")).strip().lower()
            order_id = str(order.get("id", "")).strip()
            try:
                if order.get("filled_avg_price"):
                    fill_price = float(order["filled_avg_price"])
                if order.get("filled_qty"):
                    filled_qty = float(order["filled_qty"])
            except Exception:
                pass
            if filled_qty <= 0:
                if order_id and status not in _ALPACA_TERMINAL_REJECT_STATUSES:
                    self._pending_opens[symbol] = {
                        "order_id": order_id,
                        "requested_qty": qty,
                        "submit_price": market_price,
                        "created_ts": time.time(),
                    }
                    self._execution_stats["orders_pending"] = len(self._pending_opens)
                    await self.db.log_thought(
                        "execution",
                        f"Stock BUY pending fill {symbol} qty={qty:.4f} order={order_id} status={status or 'unknown'}",
                        severity="warning",
                        tenant_id=self.tenant_id,
                    )
                    return True
                self._execution_stats["orders_rejected"] += 1
                await self.db.log_thought(
                    "execution",
                    f"Stock BUY rejected (unfilled) {symbol} qty={qty:.4f} status={status or 'unknown'}",
                    severity="warning",
                    tenant_id=self.tenant_id,
                )
                return False
            return await self._persist_open_trade(
                symbol=symbol,
                fill_price=fill_price,
                filled_qty=filled_qty,
                order=order,
            )

        return await self._persist_open_trade(
            symbol=symbol,
            fill_price=fill_price,
            filled_qty=filled_qty,
            order=None,
        )

    async def _persist_open_trade(
        self,
        *,
        symbol: str,
        fill_price: float,
        filled_qty: float,
        order: Optional[Dict[str, Any]],
        count_fill: bool = True,
    ) -> bool:
        if fill_price <= 0 or filled_qty <= 0:
            return False

        trade_id = f"S-{uuid.uuid4().hex[:12]}"
        metadata: Dict[str, Any] = {
            "asset_class": "stock",
            "min_hold_seconds": self.min_hold_seconds,
            "max_hold_seconds": self.max_hold_seconds,
            "mode": self.mode,
            "size_usd": round(fill_price * filled_qty, 2),
        }
        if order:
            oid = str(order.get("id", "")).strip()
            status = str(order.get("status", "")).strip().lower()
            if oid:
                metadata["broker_order_id"] = oid
            if status:
                metadata["broker_order_status"] = status

        await self.db.insert_trade(
            {
                "trade_id": trade_id,
                "pair": symbol,
                "side": "buy",
                "entry_price": fill_price,
                "quantity": filled_qty,
                "status": "open",
                "strategy": "stock_swing",
                "confidence": 0.65,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
            },
            tenant_id=self.tenant_id,
        )
        if count_fill:
            self._execution_stats["orders_filled"] += 1
        await self.db.log_thought(
            "execution",
            f"Stock BUY {symbol} qty={filled_qty:.4f} @ {fill_price:.2f}",
            severity="info",
            tenant_id=self.tenant_id,
        )
        return True

    async def _reconcile_pending_opens(self) -> None:
        if self.mode != "live" or not self._pending_opens:
            self._execution_stats["orders_pending"] = len(self._pending_opens)
            return

        open_rows = await self.db.get_open_trades(tenant_id=self.tenant_id)
        open_symbols = {str(row.get("pair", "")).upper() for row in open_rows}
        broker_positions = await self._normalize_broker_positions()

        for symbol in list(self._pending_opens.keys()):
            pending = self._pending_opens.get(symbol) or {}
            if symbol in open_symbols:
                self._pending_opens.pop(symbol, None)
                continue

            broker_pos = broker_positions.get(symbol)
            if broker_pos:
                opened = await self._materialize_broker_position(
                    symbol,
                    broker_pos,
                    source="pending_reconcile",
                    pending_order_id=str(pending.get("order_id", "")).strip(),
                )
                if opened:
                    self._pending_opens.pop(symbol, None)
                continue

            order_id = str(pending.get("order_id", "")).strip()
            if not order_id:
                self._pending_opens.pop(symbol, None)
                self._execution_stats["orders_rejected"] += 1
                continue

            order = await self.alpaca.get_order(order_id)
            if not order:
                age_seconds = max(
                    0.0,
                    time.time() - float(pending.get("created_ts", 0.0) or 0.0),
                )
                if age_seconds > 900:
                    self._pending_opens.pop(symbol, None)
                    self._execution_stats["orders_rejected"] += 1
                    await self.db.log_thought(
                        "execution",
                        f"Stock BUY pending timeout {symbol} order={order_id} (no broker position)",
                        severity="warning",
                        tenant_id=self.tenant_id,
                    )
                continue

            status = str(order.get("status", "")).strip().lower()
            fill_price = float(pending.get("submit_price", 0.0) or 0.0)
            filled_qty = 0.0
            try:
                if order.get("filled_avg_price"):
                    fill_price = float(order["filled_avg_price"])
                if order.get("filled_qty"):
                    filled_qty = float(order["filled_qty"])
            except Exception:
                pass

            if filled_qty > 0:
                opened = await self._persist_open_trade(
                    symbol=symbol,
                    fill_price=fill_price,
                    filled_qty=filled_qty,
                    order=order,
                )
                if opened:
                    self._pending_opens.pop(symbol, None)
                continue

            if status in _ALPACA_TERMINAL_REJECT_STATUSES:
                self._pending_opens.pop(symbol, None)
                self._execution_stats["orders_rejected"] += 1
                await self.db.log_thought(
                    "execution",
                    f"Stock BUY rejected {symbol} order={order_id} status={status}",
                    severity="warning",
                    tenant_id=self.tenant_id,
                )

        self._execution_stats["orders_pending"] = len(self._pending_opens)

    async def _maybe_close_trade(self, trade: Dict[str, Any], market_price: float, signal: str) -> bool:
        entry_time = self._parse_dt(trade.get("entry_time"))
        if not entry_time:
            return False
        held_seconds = max(0.0, (datetime.now(timezone.utc) - entry_time).total_seconds())
        if held_seconds >= self.max_hold_seconds:
            return await self._close_trade(trade, reason="max_hold_timeout", force=True)
        if held_seconds >= self.min_hold_seconds and signal == "exit":
            return await self._close_trade(trade, reason="signal_exit", force=False, market_price=market_price)
        return False

    async def _close_trade(
        self,
        trade: Dict[str, Any],
        *,
        reason: str,
        force: bool,
        market_price: Optional[float] = None,
    ) -> bool:
        symbol = str(trade.get("pair", "")).upper()
        qty = float(trade.get("quantity", 0.0) or 0.0)
        if qty <= 0:
            return False
        entry = float(trade.get("entry_price", 0.0) or 0.0)
        if entry <= 0:
            return False

        exit_price = float(market_price or self.market_data.get_latest_price(symbol) or 0.0)
        if exit_price <= 0:
            return False

        if self.mode == "live":
            broker_close = await self.alpaca.close_position(symbol)
            if broker_close is None:
                return False
            try:
                bpx = broker_close.get("filled_avg_price")
                if bpx:
                    exit_price = float(bpx)
            except Exception:
                pass

        gross_pnl = (exit_price - entry) * qty
        entry_notional = abs(entry * qty)
        exit_notional = abs(exit_price * qty)
        fee_pct = max(0.0, float(getattr(self.config.stocks, "estimated_fee_pct_per_side", 0.0005) or 0.0))
        slippage_pct = max(
            0.0,
            float(getattr(self.config.stocks, "estimated_slippage_pct_per_side", 0.0002) or 0.0),
        )
        fees = (entry_notional + exit_notional) * fee_pct
        slippage = (entry_notional + exit_notional) * slippage_pct
        pnl = gross_pnl - fees - slippage
        pnl_pct = (pnl / entry_notional) if entry_notional > 0 else 0.0
        await self.db.close_trade(
            trade["trade_id"],
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=fees,
            slippage=slippage,
            tenant_id=self.tenant_id,
        )
        self.risk_manager.record_closed_trade(pnl)
        self._execution_stats["orders_closed"] += 1
        await self.db.log_thought(
            "execution",
            (
                f"Stock CLOSE {symbol} qty={qty:.4f} @ {exit_price:.2f} reason={reason} "
                f"gross={gross_pnl:.2f} fees={fees:.2f} slippage={slippage:.2f} net={pnl:.2f}"
            ),
            severity="info",
            tenant_id=self.tenant_id,
        )
        return True

    async def _apply_runtime_breakers(self) -> None:
        mon = self.config.monitoring
        open_rows = await self.db.get_open_trades(tenant_id=self.tenant_id)
        report = self.risk_manager.get_risk_report(open_positions=len(open_rows))

        if getattr(mon, "auto_pause_on_consecutive_losses", True):
            losses = int(report.get("consecutive_losses", 0) or 0)
            threshold = max(1, int(getattr(mon, "consecutive_losses_pause_threshold", 4) or 4))
            if losses >= threshold:
                await self._auto_pause(
                    "consecutive_losses",
                    detail=f"{losses} losses >= {threshold}",
                )
                return

        if getattr(mon, "auto_pause_on_drawdown", True):
            drawdown = float(report.get("current_drawdown", 0.0) or 0.0)
            dd_limit = max(0.1, float(getattr(mon, "drawdown_pause_pct", 8.0) or 8.0))
            if drawdown >= dd_limit:
                await self._auto_pause(
                    "drawdown_limit",
                    detail=f"{drawdown:.2f}% >= {dd_limit:.2f}%",
                )

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def get_algorithm_stats(self) -> List[Dict[str, Any]]:
        total_pnl = float(self.risk_manager.current_bankroll - self.risk_manager.initial_bankroll)
        return [
            {
                "name": "stock_swing",
                "enabled": True,
                "kind": "strategy",
                "weight": 1.0,
                "trades": int(self.risk_manager._trade_count),
                "win_rate": round(float(self.risk_manager.win_rate), 4),
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(float(self.risk_manager.avg_pnl), 4),
                "note": "daily swing strategy (Polygon + Alpaca)",
            }
        ]
