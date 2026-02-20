from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pytest

from src.strategies.base import StrategySignal
from src.strategies.ichimoku import IchimokuStrategy
from src.strategies.keltner import KeltnerStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.order_flow import OrderFlowStrategy
from src.strategies.reversal import ReversalStrategy
from src.strategies.stochastic_divergence import StochasticDivergenceStrategy
from src.strategies.supertrend import SupertrendStrategy
from src.strategies.trend import TrendStrategy
from src.strategies.volatility_squeeze import VolatilitySqueezeStrategy


def _make_replay_ohlcv(seed: int, n: int = 340):
    rng = np.random.default_rng(seed)
    price = 100.0
    closes = []
    highs = []
    lows = []
    volumes = []
    opens = []
    for i in range(n):
        regime = (i // 70) % 5
        if regime == 0:
            drift = 0.0005
            sigma = 0.002
        elif regime == 1:
            drift = -0.0004
            sigma = 0.0025
        elif regime == 2:
            drift = 0.0
            sigma = 0.0015
        elif regime == 3:
            drift = 0.0008 if i % 2 == 0 else -0.0006
            sigma = 0.0032
        else:
            drift = 0.0
            sigma = 0.004

        ret = drift + float(rng.normal(0.0, sigma))
        open_price = price
        close_price = max(3.0, price * (1.0 + ret))
        wick_up = abs(float(rng.normal(0.001, sigma * 0.5)))
        wick_dn = abs(float(rng.normal(0.001, sigma * 0.5)))
        high = max(open_price, close_price) * (1.0 + wick_up)
        low = min(open_price, close_price) * max(0.01, 1.0 - wick_dn)
        volume = max(1.0, 100.0 + 20.0 * regime + float(rng.normal(0.0, 10.0)))

        opens.append(open_price)
        closes.append(close_price)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)
        price = close_price

    return (
        np.array(closes, dtype=float),
        np.array(highs, dtype=float),
        np.array(lows, dtype=float),
        np.array(volumes, dtype=float),
        np.array(opens, dtype=float),
    )


class _FakeMarketData:
    def get_order_book_analysis(self, pair: str) -> Dict[str, Any]:
        return {
            "updated_at": time.time(),
            "book_score": 0.65,
            "spread_pct": 0.0005,
            "obi": 0.35,
            "whale_bias": 0.2,
        }


def _normalize(signal: StrategySignal) -> Dict[str, Any]:
    return {
        "direction": signal.direction.value,
        "strength": round(float(signal.strength), 6),
        "confidence": round(float(signal.confidence), 6),
        "entry_price": round(float(signal.entry_price), 6),
        "stop_loss": round(float(signal.stop_loss), 6),
        "take_profit": round(float(signal.take_profit), 6),
    }


@dataclass
class ReplayCase:
    name: str
    strategy_factory: Any
    seed: int
    expected_direction: str
    extra_kwargs: Dict[str, Any]


REPLAY_CASES = [
    ReplayCase("keltner", KeltnerStrategy, 19, "long", {}),
    ReplayCase("mean_reversion", MeanReversionStrategy, 70, "short", {}),
    ReplayCase("ichimoku", IchimokuStrategy, 83, "short", {}),
    ReplayCase("order_flow", OrderFlowStrategy, 42, "long", {"market_data": _FakeMarketData()}),
    ReplayCase("trend", TrendStrategy, 1, "long", {}),
    ReplayCase("stochastic_divergence", StochasticDivergenceStrategy, 42, "neutral", {}),
    ReplayCase("volatility_squeeze", VolatilitySqueezeStrategy, 120, "long", {}),
    ReplayCase("supertrend", SupertrendStrategy, 22, "short", {}),
    ReplayCase("reversal", ReversalStrategy, 344, "short", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", REPLAY_CASES, ids=[c.name for c in REPLAY_CASES])
async def test_strategy_replay_is_deterministic(case: ReplayCase):
    closes, highs, lows, volumes, opens = _make_replay_ohlcv(case.seed)

    snapshots = []
    for _ in range(3):
        strategy = case.strategy_factory()
        signal = await strategy.analyze(
            "BTC/USD",
            closes,
            highs,
            lows,
            volumes,
            opens=opens,
            **case.extra_kwargs,
        )
        snapshots.append(_normalize(signal))

    assert snapshots[0] == snapshots[1] == snapshots[2]
    assert snapshots[0]["direction"] == case.expected_direction
