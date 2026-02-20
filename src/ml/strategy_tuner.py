"""
Automatic Strategy Tuner - DB-backed analysis to persist strategy weight
adjustments and enable/disable decisions across restarts.

Runs weekly (configurable), examines the last N closed trades per strategy,
computes Sharpe-like scores and win rates, and persists recommended changes
to config.yaml.  All changes are logged to the thought_log for dashboard
audit trails.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager, save_to_yaml
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("strategy_tuner")


class StrategyTuner:
    """Analyse closed trades and recommend per-strategy weight & enable/disable changes."""

    def __init__(
        self,
        db: DatabaseManager,
        config_path: str = "config/config.yaml",
        min_trades_per_strategy: int = 15,
        weight_bounds: tuple[float, float] = (0.05, 0.50),
        auto_disable_sharpe: float = -0.3,
        auto_disable_min_trades: int = 30,
        tenant_id: str = "default",
    ):
        self.db = db
        self.config_path = config_path
        self.min_trades = min_trades_per_strategy
        self.weight_lo, self.weight_hi = weight_bounds
        self.auto_disable_sharpe = auto_disable_sharpe
        self.auto_disable_min_trades = auto_disable_min_trades
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def tune(self) -> Dict[str, Any]:
        """Run one optimisation pass. Returns dict of changes made."""
        trades = await self.db.get_trade_history(limit=500, tenant_id=self.tenant_id)
        if not trades:
            return {"changes": [], "reason": "no closed trades"}

        # Group by strategy
        by_strat: Dict[str, List[Dict[str, Any]]] = {}
        for t in trades:
            strat = t.get("strategy")
            if strat:
                by_strat.setdefault(strat, []).append(t)

        # Load current config to read weights/enabled flags
        cfg = ConfigManager()
        strategies_cfg = cfg.config.strategies.model_dump()

        overall_pnls = [float(t.get("pnl", 0)) for t in trades if t.get("pnl") is not None]
        baseline_sharpe = self._sharpe(overall_pnls) if len(overall_pnls) >= 5 else 0.0

        changes: List[Dict[str, Any]] = []
        yaml_updates: Dict[str, Dict[str, Any]] = {"strategies": {}}

        for strat_name, strat_trades in by_strat.items():
            pnls = [float(t.get("pnl", 0)) for t in strat_trades if t.get("pnl") is not None]
            n = len(pnls)
            if n < self.min_trades:
                continue

            wins = sum(1 for p in pnls if p > 0)
            win_rate = wins / n if n > 0 else 0.0
            avg_pnl = sum(pnls) / n if n > 0 else 0.0
            sharpe = self._sharpe(pnls)

            strat_cfg = strategies_cfg.get(strat_name, {})
            current_weight = float(strat_cfg.get("weight", 0.20))
            current_enabled = strat_cfg.get("enabled", True)

            # --- Auto-disable: persistently bad ---
            if (
                n >= self.auto_disable_min_trades
                and sharpe < self.auto_disable_sharpe
                and current_enabled
            ):
                yaml_updates["strategies"][strat_name] = {"enabled": False}
                changes.append({
                    "strategy": strat_name,
                    "action": "disable",
                    "reason": f"Sharpe {sharpe:.2f} < {self.auto_disable_sharpe} over {n} trades",
                    "sharpe": round(sharpe, 3),
                    "win_rate": round(win_rate, 3),
                    "trades": n,
                })
                continue

            # --- Auto-re-enable: disabled but recently positive ---
            if not current_enabled and n >= self.min_trades and sharpe > 0:
                yaml_updates["strategies"][strat_name] = {"enabled": True}
                changes.append({
                    "strategy": strat_name,
                    "action": "re-enable",
                    "reason": f"Sharpe {sharpe:.2f} > 0 over {n} recent trades",
                    "sharpe": round(sharpe, 3),
                    "win_rate": round(win_rate, 3),
                    "trades": n,
                })

            # --- Weight adjustment ---
            if sharpe > baseline_sharpe + 0.3 and win_rate > 0.50:
                new_weight = min(current_weight * 1.15, self.weight_hi)
            elif sharpe < baseline_sharpe - 0.3:
                new_weight = max(current_weight * 0.85, self.weight_lo)
            else:
                new_weight = current_weight  # No change

            new_weight = round(new_weight, 3)
            if new_weight != current_weight:
                if strat_name not in yaml_updates["strategies"]:
                    yaml_updates["strategies"][strat_name] = {}
                yaml_updates["strategies"][strat_name]["weight"] = new_weight
                changes.append({
                    "strategy": strat_name,
                    "action": "weight",
                    "old_weight": current_weight,
                    "new_weight": new_weight,
                    "sharpe": round(sharpe, 3),
                    "win_rate": round(win_rate, 3),
                    "trades": n,
                })

        # Persist to YAML and hot-reload
        if yaml_updates["strategies"]:
            # Flatten nested structure for save_to_yaml
            flat_updates: Dict[str, Dict[str, Any]] = {}
            for section, kvs in yaml_updates.items():
                if section == "strategies":
                    for sname, skvs in kvs.items():
                        flat_key = f"strategies"
                        if flat_key not in flat_updates:
                            flat_updates[flat_key] = {}
                        # save_to_yaml expects {"strategies": {"keltner": {...}}}
                        flat_updates[flat_key][sname] = skvs

            save_to_yaml(flat_updates, self.config_path)
            cfg.reload(self.config_path)
            logger.info("Strategy tuner persisted changes", changes=len(changes))

        # Log all changes to thought_log
        if changes:
            summary = "; ".join(
                f"{c['strategy']}: {c['action']}" for c in changes
            )
            await self.db.log_thought(
                "tuner",
                f"Strategy Tuner made {len(changes)} change(s): {summary}",
                severity="info",
                metadata={"changes": changes},
                tenant_id=self.tenant_id,
            )
        else:
            await self.db.log_thought(
                "tuner",
                "Strategy Tuner: no changes needed",
                severity="debug",
                tenant_id=self.tenant_id,
            )

        return {"changes": changes, "baseline_sharpe": round(baseline_sharpe, 3)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sharpe(pnls: List[float]) -> float:
        """Simple Sharpe-like ratio: mean / std. Returns 0 if insufficient data."""
        if len(pnls) < 5:
            return 0.0
        mean = sum(pnls) / len(pnls)
        variance = sum((x - mean) ** 2 for x in pnls) / max(len(pnls) - 1, 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std < 1e-12:
            return 0.0
        return mean / std


class AutoTuner:
    """Background loop that triggers StrategyTuner on a configurable interval."""

    def __init__(self, tuner: StrategyTuner, interval_hours: int = 168):
        self.tuner = tuner
        self.interval_hours = max(1, interval_hours)
        self._last_tune_time: float = 0.0

    async def run(self) -> None:
        """Hourly check loop — triggers tuning when interval elapses."""
        logger.info("Auto-tuner started", interval_hours=self.interval_hours)
        # Don't tune immediately on startup — wait one cycle
        self._last_tune_time = time.time()

        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour

                elapsed_hours = (time.time() - self._last_tune_time) / 3600
                if elapsed_hours >= self.interval_hours:
                    logger.info("Auto-tuner triggering scheduled tune")
                    result = await self.tuner.tune()
                    self._last_tune_time = time.time()
                    n_changes = len(result.get("changes", []))
                    logger.info(
                        "Auto-tune complete",
                        changes=n_changes,
                        baseline_sharpe=result.get("baseline_sharpe"),
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Auto-tuner error", error=repr(e))
                await asyncio.sleep(300)
