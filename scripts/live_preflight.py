#!/usr/bin/env python3
"""
Live preflight validator for unattended NovaPulse runs.

Fails fast on unsafe config/env combinations before enabling real-money mode.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import load_config_with_overrides
from src.core.multi_engine import resolve_exchange_names, resolve_trading_accounts


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on", "y")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_for_account(account_id: str, name: str, default: str = "") -> str:
    account = (account_id or "").strip().lower()
    if account and account != "default":
        prefix = "".join(ch if ch.isalnum() else "_" for ch in account.upper())
        scoped_name = f"{prefix}_{name}"
        scoped_val = (os.getenv(scoped_name) or "").strip()
        if scoped_val:
            return scoped_val
    return (os.getenv(name) or default).strip()


def run_preflight(require_live: bool = True, strict: bool = False) -> int:
    cfg = load_config_with_overrides()
    errors: List[str] = []
    warnings: List[str] = []

    mode = (cfg.app.mode or "").strip().lower()
    live_checks = (mode == "live") or require_live
    cfg_exchanges = getattr(cfg.app, "trading_exchanges", "").strip()
    if cfg_exchanges and not (os.getenv("TRADING_EXCHANGES") or "").strip():
        os.environ["TRADING_EXCHANGES"] = cfg_exchanges
    if require_live and mode != "live":
        errors.append("`app.mode` must be `live` for live preflight.")
    if mode == "live" and _truthy(_env("START_PAUSED")):
        warnings.append("`START_PAUSED=true` is set; bot will require manual resume after startup.")

    # Exchange credentials (supports multi-exchange and multi-account routing).
    exchange_names = resolve_exchange_names(cfg.exchange.name) or [(cfg.exchange.name or "").strip().lower()]
    account_specs = resolve_trading_accounts(
        cfg.exchange.name,
        getattr(cfg.app, "trading_accounts", "").strip(),
    )
    if not account_specs:
        account_specs = [{"account_id": "default", "exchange": (cfg.exchange.name or "kraken").strip().lower()}]
    if mode == "live":
        for spec in account_specs:
            account_id = str(spec.get("account_id") or "default").strip().lower()
            ex = str(spec.get("exchange") or cfg.exchange.name or "kraken").strip().lower()
            scope_label = f"{account_id}:{ex}"
            if ex == "kraken":
                if not _env_for_account(account_id, "KRAKEN_API_KEY"):
                    errors.append(f"Missing `KRAKEN_API_KEY` for Kraken live mode ({scope_label}).")
                if not _env_for_account(account_id, "KRAKEN_API_SECRET"):
                    errors.append(f"Missing `KRAKEN_API_SECRET` for Kraken live mode ({scope_label}).")
            elif ex == "coinbase":
                key_name = _env_for_account(account_id, "COINBASE_KEY_NAME")
                org_id = _env_for_account(account_id, "COINBASE_ORG_ID")
                key_id = _env_for_account(account_id, "COINBASE_KEY_ID")
                private_key_inline = _env_for_account(account_id, "COINBASE_PRIVATE_KEY")
                private_key_path = _env_for_account(account_id, "COINBASE_PRIVATE_KEY_PATH")
                has_key_name = bool(key_name or (org_id and key_id))
                has_private_key = bool(private_key_inline or private_key_path)
                if not has_key_name or not has_private_key:
                    errors.append(
                        "Coinbase live mode requires key identity + private key material "
                        f"(`COINBASE_PRIVATE_KEY` or `COINBASE_PRIVATE_KEY_PATH`) for {scope_label}."
                    )
            else:
                errors.append(f"Unsupported exchange `{ex}` in trading account list ({scope_label}).")

    # Dashboard/auth hardening for unattended remote control
    if mode == "live":
        if not _env("DASHBOARD_ADMIN_KEY"):
            errors.append("Missing `DASHBOARD_ADMIN_KEY` in live mode.")
        if not _env("DASHBOARD_SESSION_SECRET"):
            errors.append("Missing `DASHBOARD_SESSION_SECRET` in live mode.")
        if not _env("DASHBOARD_ADMIN_PASSWORD_HASH"):
            errors.append("Missing `DASHBOARD_ADMIN_PASSWORD_HASH` in live mode.")
    if not cfg.dashboard.require_api_key_for_reads:
        warnings.append("`dashboard.require_api_key_for_reads` is false; enable it for unattended operation.")

    # Trade/risk envelope
    if cfg.risk.max_risk_per_trade > 0.01:
        msg = (
            f"`risk.max_risk_per_trade={cfg.risk.max_risk_per_trade}` too high for unattended mode "
            "(recommended <= 0.01)."
        )
        (errors if live_checks else warnings).append(msg)
    if cfg.trading.max_trades_per_hour <= 0:
        msg = "`trading.max_trades_per_hour` must be > 0 to prevent runaway entry loops."
        (errors if live_checks else warnings).append(msg)
    if cfg.trading.max_trades_per_hour > 12:
        warnings.append(f"`trading.max_trades_per_hour={cfg.trading.max_trades_per_hour}` is aggressive.")

    if cfg.risk.initial_bankroll > 0:
        pos_frac = cfg.risk.max_position_usd / cfg.risk.initial_bankroll
        if pos_frac > 0.05:
            warnings.append(
                f"`risk.max_position_usd` is {pos_frac:.1%} of bankroll; "
                "recommended <= 5% for unattended windows."
            )

    if cfg.trading.max_concurrent_positions > 2 and not cfg.trading.canary_mode:
        warnings.append(
            "`trading.max_concurrent_positions` > 2 while canary is disabled; "
            "consider canary or fewer concurrent positions."
        )

    if not cfg.trading.canary_mode:
        warnings.append("Canary mode is disabled. For first live month, canary mode is strongly recommended.")

    # Stocks swing stack (Polygon + Alpaca)
    if cfg.stocks.enabled:
        if cfg.stocks.min_hold_days < 1:
            errors.append("`stocks.min_hold_days` must be >= 1 for swing mode.")
        if cfg.stocks.max_hold_days < cfg.stocks.min_hold_days:
            errors.append("`stocks.max_hold_days` must be >= `stocks.min_hold_days`.")
        if cfg.stocks.max_hold_days > 30:
            warnings.append("`stocks.max_hold_days` is high; current pilot target is <= 7 days.")
        if mode == "live":
            if not (cfg.stocks.polygon_api_key or _env("POLYGON_API_KEY")):
                errors.append("Stocks enabled but Polygon API key is missing (`POLYGON_API_KEY`).")
            if not (cfg.stocks.alpaca_api_key or _env("ALPACA_API_KEY")):
                errors.append("Stocks enabled but Alpaca API key is missing (`ALPACA_API_KEY`).")
            if not (cfg.stocks.alpaca_api_secret or _env("ALPACA_API_SECRET")):
                errors.append("Stocks enabled but Alpaca API secret is missing (`ALPACA_API_SECRET`).")

    # Circuit breakers
    mon = cfg.monitoring
    if not mon.auto_pause_on_stale_data:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_stale_data` must be true.")
    if not mon.auto_pause_on_ws_disconnect:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_ws_disconnect` must be true.")
    if not mon.auto_pause_on_consecutive_losses:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_consecutive_losses` must be true.")
    if mon.consecutive_losses_pause_threshold > 5:
        warnings.append(
            f"`monitoring.consecutive_losses_pause_threshold={mon.consecutive_losses_pause_threshold}` is high."
        )
    if not mon.auto_pause_on_drawdown:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_drawdown` must be true.")
    if mon.drawdown_pause_pct > 10.0:
        warnings.append(f"`monitoring.drawdown_pause_pct={mon.drawdown_pause_pct}` is high for unattended mode.")

    # DB path sanity
    db_path = Path(cfg.app.db_path)
    db_parent = db_path.parent if db_path.parent else Path(".")
    try:
        db_parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Cannot create DB directory `{db_parent}`: {e}")
    if str(cfg.app.db_path).strip() in (":memory:", ""):
        errors.append("`app.db_path` must be a persistent file path (not `:memory:`).")

    # Optional ES pipeline checks
    if cfg.elasticsearch.enabled:
        has_cloud = bool(cfg.elasticsearch.cloud_id.strip())
        has_hosts = bool(cfg.elasticsearch.hosts)
        if not (has_cloud or has_hosts):
            errors.append("Elasticsearch enabled but no `cloud_id` or `hosts` configured.")
        if not (cfg.elasticsearch.api_key or _env("ES_API_KEY")):
            errors.append("Elasticsearch enabled but no API key configured (`ES_API_KEY` or config value).")

    print("NovaPulse Live Preflight")
    print(
        f"mode={cfg.app.mode} exchanges={','.join(exchange_names)} accounts={len(account_specs)} "
        f"canary={cfg.trading.canary_mode} stocks={cfg.stocks.enabled}"
    )
    if errors:
        print("\nFAILURES:")
        for item in errors:
            print(f" - {item}")
    if warnings:
        print("\nWARNINGS:")
        for item in warnings:
            print(f" - {item}")

    if errors:
        return 1
    if strict and warnings:
        return 2
    print("\nPASS: preflight checks passed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate unattended live readiness for NovaPulse.")
    parser.add_argument(
        "--allow-paper",
        action="store_true",
        help="Allow preflight in non-live mode.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when warnings exist.",
    )
    args = parser.parse_args()
    raise SystemExit(run_preflight(require_live=not args.allow_paper, strict=args.strict))


if __name__ == "__main__":
    main()
