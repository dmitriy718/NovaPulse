#!/usr/bin/env python3
"""
Walk-forward out-of-sample gate for CI.

Runs deterministic synthetic OHLCV through the backtester in rolling windows,
selects a train-window confluence threshold, and validates OOS metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

# Ensure repository root is importable when script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ml.backtester import Backtester, BacktestResult


@dataclass
class SplitResult:
    split_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    selected_threshold: int
    result: BacktestResult


def _generate_synthetic_ohlcv(n_bars: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prices = [100.0]
    opens: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    volumes: List[float] = []
    base_ts = 1_700_000_000

    for i in range(n_bars):
        regime = (i // 240) % 4
        if regime == 0:  # up trend
            drift = 0.00028
            sigma = 0.0018
            vol_base = 120.0
        elif regime == 1:  # down trend
            drift = -0.00025
            sigma = 0.0022
            vol_base = 135.0
        elif regime == 2:  # range
            drift = 0.00003 * math.sin(i / 21.0)
            sigma = 0.0014
            vol_base = 95.0
        else:  # high-vol chop
            drift = 0.00007 * math.sin(i / 11.0)
            sigma = 0.0028
            vol_base = 150.0

        prev = prices[-1]
        ret = drift + float(rng.normal(0.0, sigma))
        close = max(5.0, prev * (1.0 + ret))
        open_ = prev

        wick_up = abs(float(rng.normal(0.0007, sigma * 0.65)))
        wick_dn = abs(float(rng.normal(0.0007, sigma * 0.65)))
        high = max(open_, close) * (1.0 + wick_up)
        low = min(open_, close) * max(0.01, 1.0 - wick_dn)

        volume = max(1.0, vol_base + float(rng.normal(0.0, vol_base * 0.08)))

        prices.append(close)
        opens.append(open_)
        highs.append(high)
        lows.append(low)
        closes.append(close)
        volumes.append(volume)

    return pd.DataFrame(
        {
            "time": [base_ts + i * 60 for i in range(n_bars)],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _score_train_result(result: BacktestResult) -> float:
    if result.total_trades <= 0:
        return -1_000.0
    return (
        result.total_return_pct
        - (result.max_drawdown * 100.0 * 0.7)
        + (result.win_rate * 10.0)
    )


async def _run_split(
    backtester: Backtester,
    pair: str,
    frame: pd.DataFrame,
    train_start: int,
    train_end: int,
    test_end: int,
    candidates: List[int],
    split_index: int,
) -> SplitResult:
    train_df = frame.iloc[train_start:train_end].reset_index(drop=True)
    test_df = frame.iloc[train_end:test_end].reset_index(drop=True)

    best_threshold = candidates[0]
    best_score = -1_000_000.0

    for threshold in candidates:
        train_result = await backtester.run(
            pair=pair,
            ohlcv_data=train_df,
            confluence_threshold=threshold,
            mode="simple",
        )
        score = _score_train_result(train_result)
        if score > best_score:
            best_score = score
            best_threshold = threshold

    oos_result = await backtester.run(
        pair=pair,
        ohlcv_data=test_df,
        confluence_threshold=best_threshold,
        mode="simple",
    )
    return SplitResult(
        split_index=split_index,
        train_start=train_start,
        train_end=train_end,
        test_start=train_end,
        test_end=test_end,
        selected_threshold=best_threshold,
        result=oos_result,
    )


def _aggregate_oos(splits: List[SplitResult], initial_balance: float) -> Dict[str, float]:
    all_trades = [trade for split in splits for trade in split.result.trades]
    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if float(t.get("pnl", 0.0)) > 0)
    total_pnl = sum(float(t.get("pnl", 0.0)) for t in all_trades)

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in all_trades if float(t.get("pnl", 0.0)) > 0)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in all_trades if float(t.get("pnl", 0.0)) < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    max_drawdown = max((split.result.max_drawdown for split in splits), default=0.0)
    win_rate = (total_wins / total_trades) if total_trades > 0 else 0.0

    pnl_pcts = np.array([float(t.get("pnl_pct", 0.0)) for t in all_trades], dtype=float)
    if len(pnl_pcts) >= 2 and float(np.std(pnl_pcts)) > 0:
        sharpe = float(np.mean(pnl_pcts) / np.std(pnl_pcts)) * math.sqrt(len(pnl_pcts))
    else:
        sharpe = 0.0

    total_initial = initial_balance * max(len(splits), 1)
    total_return_pct = (total_pnl / total_initial) * 100.0 if total_initial > 0 else 0.0

    return {
        "splits": float(len(splits)),
        "total_trades": float(total_trades),
        "win_rate": win_rate,
        "total_return_pct": total_return_pct,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe,
    }


async def _run_gate(args: argparse.Namespace) -> int:
    frame = _generate_synthetic_ohlcv(args.bars, args.seed)
    backtester = Backtester(
        initial_balance=args.initial_balance,
        risk_per_trade=args.risk_per_trade,
        max_position_pct=args.max_position_pct,
        slippage_pct=args.slippage_pct,
        fee_pct=args.fee_pct,
    )

    candidates = [int(x.strip()) for x in args.candidates.split(",") if x.strip()]
    if not candidates:
        raise ValueError("No confluence threshold candidates provided.")

    splits: List[SplitResult] = []
    split_idx = 0
    for start in range(0, len(frame) - args.train_bars - args.test_bars + 1, args.step_bars):
        train_start = start
        train_end = start + args.train_bars
        test_end = train_end + args.test_bars
        split_idx += 1
        split = await _run_split(
            backtester=backtester,
            pair=args.pair,
            frame=frame,
            train_start=train_start,
            train_end=train_end,
            test_end=test_end,
            candidates=candidates,
            split_index=split_idx,
        )
        splits.append(split)

    if not splits:
        print("FAIL: No walk-forward splits generated.")
        return 2

    agg = _aggregate_oos(splits, args.initial_balance)
    print("Walk-forward OOS summary")
    print(
        f"splits={int(agg['splits'])} trades={int(agg['total_trades'])} "
        f"win_rate={agg['win_rate']:.3f} return={agg['total_return_pct']:.2f}% "
        f"max_dd={agg['max_drawdown']:.3f} pf={agg['profit_factor']:.3f} "
        f"sharpe={agg['sharpe_ratio']:.3f}"
    )
    for split in splits:
        d = split.result.to_dict()
        print(
            f"split={split.split_index} train=[{split.train_start},{split.train_end}) "
            f"test=[{split.test_start},{split.test_end}) th={split.selected_threshold} "
            f"trades={d['total_trades']} win_rate={d['win_rate']:.3f} "
            f"ret={d['total_return_pct']:.2f}% dd={d['max_drawdown']:.3f} "
            f"pf={d['profit_factor']:.3f}"
        )

    failures = []
    if agg["total_trades"] < args.min_trades:
        failures.append(f"total_trades {agg['total_trades']:.0f} < {args.min_trades}")
    if agg["win_rate"] < args.min_win_rate:
        failures.append(f"win_rate {agg['win_rate']:.3f} < {args.min_win_rate:.3f}")
    if agg["total_return_pct"] < args.min_return_pct:
        failures.append(f"return {agg['total_return_pct']:.2f}% < {args.min_return_pct:.2f}%")
    if agg["max_drawdown"] > args.max_drawdown:
        failures.append(f"max_drawdown {agg['max_drawdown']:.3f} > {args.max_drawdown:.3f}")
    if agg["profit_factor"] < args.min_profit_factor:
        failures.append(f"profit_factor {agg['profit_factor']:.3f} < {args.min_profit_factor:.3f}")
    if agg["sharpe_ratio"] < args.min_sharpe:
        failures.append(f"sharpe {agg['sharpe_ratio']:.3f} < {args.min_sharpe:.3f}")

    if failures:
        print("FAIL: Walk-forward OOS gate did not pass.")
        for reason in failures:
            print(f" - {reason}")
        return 1

    print("PASS: Walk-forward OOS gate passed.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Walk-forward out-of-sample CI gate.")
    parser.add_argument("--pair", default="BTC/USD")
    parser.add_argument("--bars", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--train-bars", type=int, default=420)
    parser.add_argument("--test-bars", type=int, default=180)
    parser.add_argument("--step-bars", type=int, default=180)
    parser.add_argument("--candidates", default="1,2,3")
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.02)
    parser.add_argument("--max-position-pct", type=float, default=0.05)
    parser.add_argument("--slippage-pct", type=float, default=0.001)
    parser.add_argument("--fee-pct", type=float, default=0.0026)

    # Gate thresholds (can be tuned in CI without code changes)
    parser.add_argument("--min-trades", type=float, default=5)
    parser.add_argument("--min-win-rate", type=float, default=0.30)
    parser.add_argument("--min-return-pct", type=float, default=-1.0)
    parser.add_argument("--max-drawdown", type=float, default=0.35)
    parser.add_argument("--min-profit-factor", type=float, default=0.60)
    parser.add_argument("--min-sharpe", type=float, default=-0.70)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    code = asyncio.run(_run_gate(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
