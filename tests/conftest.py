"""Shared test fixtures and stubs for NovaPulse tests.

Provides reusable stub classes and factory functions for executor,
risk manager, market data, and database testing.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.config import ConfigManager
from src.execution.executor import TradeExecutor
from src.execution.risk_manager import RiskManager, StopLossState
from src.ai.confluence import ConfluenceSignal
from src.strategies.base import SignalDirection, StrategySignal


# ---------------------------------------------------------------------------
# Stub classes
# ---------------------------------------------------------------------------


class StubDB:
    """Full-featured async DB stub for executor tests.

    Configurable via attributes:
        _open_trades: list of trade dicts returned by get_open_trades()
        _count_trades_since_value: int returned by count_trades_since()
        _performance_stats: dict returned by get_performance_stats()
    """

    def __init__(
        self,
        open_trades: Optional[List[Dict[str, Any]]] = None,
        count_trades_since_value: int = 0,
    ) -> None:
        self._open_trades: List[Dict[str, Any]] = open_trades or []
        self._count_trades_since_value = count_trades_since_value
        self._performance_stats: Dict[str, Any] = {
            "total_trades": 0,
            "win_rate": 0.5,
            "avg_win": 1.0,
            "avg_loss": -1.0,
        }
        # Tracking attributes for assertions
        self.trades: List[Dict[str, Any]] = []
        self.updates: List[tuple] = []
        self.thoughts: List[tuple] = []
        self.closed_trades: List[str] = []
        self.count_calls: int = 0
        self.is_initialized = True

    async def get_open_trades(self, pair=None, tenant_id=None):
        if pair is not None:
            return [t for t in self._open_trades if t.get("pair") == pair]
        return list(self._open_trades)

    async def insert_trade(self, trade_record, tenant_id=None):
        self.trades.append(trade_record)

    async def update_trade(self, trade_id, updates, tenant_id=None):
        self.updates.append((trade_id, updates, tenant_id))

    async def close_trade(self, trade_id, exit_price, pnl, pnl_pct, fees, tenant_id=None):
        self.closed_trades.append(trade_id)

    async def log_thought(self, *args, **kwargs):
        self.thoughts.append((args, kwargs))

    async def count_trades_since(self, cutoff, tenant_id=None):
        self.count_calls += 1
        return self._count_trades_since_value

    async def get_performance_stats(self, tenant_id=None):
        return dict(self._performance_stats)

    async def insert_ml_features(self, pair, features, label, trade_id, tenant_id=None):
        pass

    async def insert_order_book_snapshot(self, **kwargs):
        pass

    async def update_ml_label_for_trade(self, trade_id, label, tenant_id=None):
        pass

    async def get_ml_features_for_trade(self, trade_id, tenant_id=None):
        return None

    async def get_thoughts(self, limit=50, tenant_id=None):
        return []

    async def insert_metric(self, name, value, tenant_id=None):
        pass

    async def cleanup_old_data(self, retention_hours=168):
        pass


class StubMarketData:
    """Market data stub with configurable prices.

    Configurable via attributes:
        _prices: dict of pair -> price
        _stale_pairs: set of pairs that are stale
    """

    def __init__(
        self,
        prices: Optional[Dict[str, float]] = None,
        stale_pairs: Optional[set] = None,
    ) -> None:
        self._prices = prices or {"BTC/USD": 50000.0, "ETH/USD": 3000.0}
        self._stale_pairs = stale_pairs or set()

    def get_latest_price(self, pair: str) -> float:
        return self._prices.get(pair, 100.0)

    def get_spread(self, pair: str) -> float:
        return 0.001

    def get_ticker(self, pair: str):
        price = self._prices.get(pair, 50000.0)
        return {"a": [str(price)], "b": [str(price - 10)]}

    def is_stale(self, pair: str, max_age_seconds: int = 120) -> bool:
        return pair in self._stale_pairs

    def get_order_book(self, pair: str):
        price = self._prices.get(pair, 50000.0)
        return {
            "bids": [[price - 10, 1.0], [price - 20, 2.0]],
            "asks": [[price, 1.0], [price + 10, 2.0]],
            "updated_at": time.time(),
        }

    def get_bar_count(self, pair: str) -> int:
        return 10


class StubRiskManager:
    """Configurable risk manager stub.

    Attributes:
        state: StopLossState returned by update_stop_loss()
        should_stop: whether should_stop_out() returns True
        closed: list of (trade_id, pnl) recorded by close_position()
    """

    def __init__(self, stop_price: float = 95.0, should_stop: bool = False) -> None:
        self.state = StopLossState(initial_sl=stop_price, current_sl=stop_price)
        self.should_stop = should_stop
        self.closed: List[tuple] = []
        self._open_positions: Dict[str, Any] = {}
        self._stop_states: Dict[str, StopLossState] = {}

    def update_stop_loss(self, trade_id, current_price, entry_price, side):
        return self.state

    def should_stop_out(self, trade_id, current_price, side):
        return self.should_stop

    def close_position(self, trade_id, pnl):
        self.closed.append((trade_id, pnl))

    def register_position(self, trade_id, pair, side, entry_price, size_usd, strategy=None):
        self._open_positions[trade_id] = {
            "pair": pair, "side": side, "entry_price": entry_price,
            "size_usd": size_usd, "strategy": strategy,
        }

    def initialize_stop_loss(self, trade_id, entry_price, stop_loss, side,
                             trailing_high=0.0, trailing_low=float("inf")):
        state = StopLossState(initial_sl=stop_loss, current_sl=stop_loss,
                              trailing_high=trailing_high, trailing_low=trailing_low)
        self._stop_states[trade_id] = state
        return state

    def reduce_position_size(self, trade_id, reduction_fraction=None, reduction_usd=0.0):
        return None

    def is_strategy_on_cooldown(self, pair, strategy, side):
        return False

    def calculate_position_size(self, **kwargs):
        from src.execution.risk_manager import PositionSizeResult
        return PositionSizeResult(
            allowed=True,
            size_units=0.01,
            size_usd=500.0,
            risk_amount=50.0,
            kelly_fraction=0.02,
        )

    def get_risk_report(self):
        return {"bankroll": 100_000.0, "current_drawdown": 0.0, "risk_of_ruin": 0.0}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def make_signal(
    pair: str = "BTC/USD",
    direction: SignalDirection = SignalDirection.LONG,
    confidence: float = 0.70,
    strength: float = 0.80,
    entry_price: float = 50000.0,
    stop_loss: float = 48500.0,
    take_profit: float = 52500.0,
    timestamp: Optional[str] = None,
    obi: float = 0.3,
    book_score: float = 0.2,
    obi_agrees: bool = True,
    is_sure_fire: bool = True,
) -> ConfluenceSignal:
    """Build a standard ConfluenceSignal with sensible defaults."""
    strategy_signal = StrategySignal(
        strategy_name="keltner",
        pair=pair,
        direction=direction,
        strength=strength,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    sig = ConfluenceSignal(
        pair=pair,
        direction=direction,
        confidence=confidence,
        strength=strength,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        signals=[strategy_signal],
        confluence_count=3,
        obi=obi,
        book_score=book_score,
        obi_agrees=obi_agrees,
        is_sure_fire=is_sure_fire,
    )
    if timestamp is not None:
        sig.timestamp = timestamp
    return sig


def make_executor(
    db: Optional[StubDB] = None,
    market_data: Optional[StubMarketData] = None,
    risk_manager=None,
    mode: str = "paper",
    use_real_risk_manager: bool = False,
    max_trades_per_hour: int = 0,
    quiet_hours_utc: Optional[tuple] = None,
) -> tuple[TradeExecutor, Any]:
    """Build a TradeExecutor wired to stubs.

    Returns (executor, risk_manager) tuple so tests can inspect the RM.
    """
    _db = db or StubDB()
    _md = market_data or StubMarketData()
    if use_real_risk_manager:
        _rm = RiskManager(initial_bankroll=100_000, max_concurrent_positions=10)
    else:
        _rm = risk_manager or StubRiskManager()
    executor = TradeExecutor(
        rest_client=None,
        market_data=_md,
        risk_manager=_rm,
        db=_db,
        mode=mode,
        max_trades_per_hour=max_trades_per_hour,
        quiet_hours_utc=quiet_hours_utc,
    )
    return executor, _rm


def make_trade(
    trade_id: str = "T-test-001",
    pair: str = "BTC/USD",
    side: str = "buy",
    entry_price: float = 50000.0,
    quantity: float = 0.1,
    stop_loss: float = 48500.0,
    take_profit: float = 52500.0,
    strategy: str = "keltner",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a trade record dict matching the shape returned by db.get_open_trades()."""
    meta = metadata if metadata is not None else {"size_usd": entry_price * quantity}
    return {
        "trade_id": trade_id,
        "pair": pair,
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "strategy": strategy,
        "status": "open",
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "metadata": json.dumps(meta) if isinstance(meta, dict) else meta,
    }


def make_dashboard_engine(
    exchange_name: str = "kraken",
    tenant_id: str = "default",
    mode: str = "paper",
    paused: bool = False,
) -> SimpleNamespace:
    """Build a minimal mock engine for DashboardServer tests."""
    return SimpleNamespace(
        db=StubDB(),
        market_data=StubMarketData(),
        risk_manager=StubRiskManager(),
        exchange_name=exchange_name,
        tenant_id=tenant_id,
        pairs=["BTC/USD"],
        mode=mode,
        _running=True,
        _trading_paused=paused,
        _priority_paused=False,
        _start_time=0,
        _scan_count=0,
        ws_client=SimpleNamespace(is_connected=True),
        config=SimpleNamespace(
            app=SimpleNamespace(mode=mode),
            billing=SimpleNamespace(
                tenant=SimpleNamespace(default_tenant_id="default"),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Auto-use fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """Prevent ConfigManager singleton state from leaking between tests."""
    saved_instance = ConfigManager._instance
    saved_config = ConfigManager._config
    yield
    ConfigManager._instance = saved_instance
    ConfigManager._config = saved_config
