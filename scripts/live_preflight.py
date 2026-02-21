#!/usr/bin/env python3
"""
Live preflight validator for unattended NovaPulse runs.

Fails fast on unsafe config/env combinations before enabling real-money mode.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import load_config_with_overrides
from src.core.multi_engine import resolve_exchange_names, resolve_trading_accounts


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on", "y")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _is_op_reference(value: str) -> bool:
    return (value or "").strip().startswith("op://")


def _op_ref_field_name(value: str) -> str:
    raw = (value or "").strip()
    if not _is_op_reference(raw):
        return ""
    # op://vault/item/field
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return ""
    return parts[-1].strip().upper()


def _env_for_account(account_id: str, name: str, default: str = "") -> str:
    account = (account_id or "").strip().lower()
    if account and account != "default":
        prefix = "".join(ch if ch.isalnum() else "_" for ch in account.upper())
        scoped_name = f"{prefix}_{name}"
        scoped_val = (os.getenv(scoped_name) or "").strip()
        if scoped_val:
            return scoped_val
    return (os.getenv(name) or default).strip()


def _collect_1password_field_labels() -> Tuple[Set[str], List[str]]:
    """Best-effort: load available 1Password field labels using service account token."""
    labels: Set[str] = set()
    warnings: List[str] = []
    token = _env("OP_SERVICE_ACCOUNT_TOKEN")
    if not token:
        return labels, warnings
    env = dict(os.environ)
    env["OP_SERVICE_ACCOUNT_TOKEN"] = token
    try:
        vaults_raw = subprocess.check_output(
            ["op", "vault", "list", "--format", "json"],
            env=env,
            text=True,
            stderr=subprocess.STDOUT,
        )
        vaults = json.loads(vaults_raw)
    except Exception as e:
        warnings.append(f"1Password discovery failed: {e}")
        return labels, warnings

    wanted = [v.strip() for v in _env("OP_VAULTS").split(",") if v.strip()]
    selected = []
    for vault in vaults:
        name = str(vault.get("name") or "").strip()
        vid = str(vault.get("id") or "").strip()
        if not wanted or name in wanted or vid in wanted:
            selected.append(vault)
    if not selected:
        selected = vaults

    for vault in selected:
        vault_name = str(vault.get("name") or vault.get("id") or "").strip()
        if not vault_name:
            continue
        try:
            items_raw = subprocess.check_output(
                ["op", "item", "list", "--vault", vault_name, "--format", "json"],
                env=env,
                text=True,
                stderr=subprocess.STDOUT,
            )
            items = json.loads(items_raw)
        except Exception as e:
            warnings.append(f"1Password list failed for vault `{vault_name}`: {e}")
            continue

        for item in items:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            try:
                full_raw = subprocess.check_output(
                    ["op", "item", "get", item_id, "--vault", vault_name, "--format", "json"],
                    env=env,
                    text=True,
                    stderr=subprocess.STDOUT,
                )
                full = json.loads(full_raw)
            except Exception:
                continue
            for field in full.get("fields", []) or []:
                label = str(field.get("label") or field.get("id") or "").strip()
                if label:
                    labels.add(label.upper())
    return labels, warnings


def _secret_present(
    name: str,
    *,
    account_id: str = "default",
    op_fields: Set[str],
    aliases: Sequence[str] = (),
) -> bool:
    keys: List[str] = [name, *aliases]
    account = (account_id or "").strip().lower()
    prefixed: List[str] = []
    if account and account != "default":
        prefix = "".join(ch if ch.isalnum() else "_" for ch in account.upper())
        prefixed = [f"{prefix}_{k}" for k in keys]

    for env_key in [*prefixed, *keys]:
        raw = _env(env_key)
        if not raw:
            continue
        if _is_op_reference(raw):
            # If env uses op:// reference, verify that referenced field exists in vault inventory.
            ref_field = _op_ref_field_name(raw)
            if ref_field and ref_field in op_fields:
                return True
            continue
        return True

    # Fallback: secret exists in 1Password inventory by label.
    for k in keys:
        if k.upper() in op_fields:
            return True
    return False


def _compute_readiness_scores(
    *,
    mode_ok: bool,
    exchange_ok: bool,
    dashboard_ok: bool,
    risk_ok: bool,
    breakers_ok: bool,
    db_ok: bool,
    read_auth_ok: bool,
    secrets_ok: bool,
    stocks_ok: bool,
    es_ok: bool,
    cfg,
    account_specs: List[Dict[str, str]],
    op_fields: Set[str],
) -> Tuple[int, int, Dict[str, bool]]:
    pilot_checks: Dict[str, bool] = {
        "mode_guard": mode_ok,
        "exchange_credentials": exchange_ok,
        "dashboard_auth": dashboard_ok,
        "risk_envelope": risk_ok,
        "circuit_breakers": breakers_ok,
        "db_persistence": db_ok,
        "read_auth": read_auth_ok,
        "secret_resolution": secrets_ok,
        "stocks_stack": stocks_ok,
        "elasticsearch_stack": es_ok,
    }
    pilot_score = round(10 * (sum(1 for v in pilot_checks.values() if v) / len(pilot_checks)))

    has_multi_account = len(account_specs) >= 2
    has_billing_primitives = any(
        _secret_present(k, op_fields=op_fields)
        for k in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_RESTRICTED_KEY")
    )
    has_billing_runtime_core = all(
        _secret_present(k, op_fields=op_fields)
        for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")
    )
    has_billing_price = any(
        _secret_present(k, op_fields=op_fields)
        for k in ("STRIPE_PRICE_ID", "STRIPE_PRICE_ID_PRO", "STRIPE_PRICE_ID_PREMIUM")
    )
    has_billing_runtime = has_billing_runtime_core and has_billing_price
    scale_checks: Dict[str, bool] = {
        "pilot_baseline": pilot_score >= 9,
        "dashboard_rate_limits": bool(cfg.dashboard.rate_limit_enabled and cfg.dashboard.rate_limit_requests_per_minute > 0),
        "ops_auto_restart": bool(cfg.monitoring.auto_restart),
        "health_interval": int(cfg.monitoring.health_check_interval) <= 60,
        "risk_limits": float(cfg.risk.max_risk_per_trade) <= 0.015 and int(cfg.trading.max_trades_per_hour) > 0,
        "webhook_security": (not bool(cfg.webhooks.enabled)) or _secret_present("SIGNAL_WEBHOOK_SECRET", op_fields=op_fields),
        "billing_stack": has_billing_runtime if bool(cfg.billing.stripe.enabled) else has_billing_primitives,
        "secret_manager_connected": not any(_is_op_reference(_env(k)) for k in os.environ.keys()) or bool(op_fields),
        "multi_account_routing": has_multi_account,
        "ci_test_gate_present": Path(".github/workflows/tests.yml").exists(),
    }
    scale_score = round(10 * (sum(1 for v in scale_checks.values() if v) / len(scale_checks)))
    checks = {**pilot_checks, **{f"scale.{k}": v for k, v in scale_checks.items()}}
    return pilot_score, scale_score, checks


def run_preflight(
    require_live: bool = True,
    strict: bool = False,
    min_pilot_score: int | None = None,
    min_scale_score: int | None = None,
) -> int:
    cfg = load_config_with_overrides()
    errors: List[str] = []
    warnings: List[str] = []
    op_fields, op_warnings = _collect_1password_field_labels()
    warnings.extend(op_warnings)

    mode = (cfg.app.mode or "").strip().lower()
    live_checks = (mode == "live") or require_live
    mode_ok = (mode == "live") if require_live else True
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
    exchange_ok = True
    if mode == "live":
        for spec in account_specs:
            account_id = str(spec.get("account_id") or "default").strip().lower()
            ex = str(spec.get("exchange") or cfg.exchange.name or "kraken").strip().lower()
            scope_label = f"{account_id}:{ex}"
            if ex == "kraken":
                if not _secret_present("KRAKEN_API_KEY", account_id=account_id, op_fields=op_fields):
                    errors.append(f"Missing `KRAKEN_API_KEY` for Kraken live mode ({scope_label}).")
                    exchange_ok = False
                if not _secret_present("KRAKEN_API_SECRET", account_id=account_id, op_fields=op_fields):
                    errors.append(f"Missing `KRAKEN_API_SECRET` for Kraken live mode ({scope_label}).")
                    exchange_ok = False
            elif ex == "coinbase":
                key_name = _secret_present("COINBASE_KEY_NAME", account_id=account_id, op_fields=op_fields)
                org_id = _secret_present("COINBASE_ORG_ID", account_id=account_id, op_fields=op_fields)
                key_id = _secret_present("COINBASE_KEY_ID", account_id=account_id, op_fields=op_fields)
                private_key_inline = _secret_present("COINBASE_PRIVATE_KEY", account_id=account_id, op_fields=op_fields)
                private_key_path = bool(_env_for_account(account_id, "COINBASE_PRIVATE_KEY_PATH"))
                has_key_name = bool(key_name or (org_id and key_id))
                has_private_key = bool(private_key_inline or private_key_path)
                if not has_key_name or not has_private_key:
                    errors.append(
                        "Coinbase live mode requires key identity + private key material "
                        f"(`COINBASE_PRIVATE_KEY` or `COINBASE_PRIVATE_KEY_PATH`) for {scope_label}."
                    )
                    exchange_ok = False
            else:
                errors.append(f"Unsupported exchange `{ex}` in trading account list ({scope_label}).")
                exchange_ok = False

    # Dashboard/auth hardening for unattended remote control
    dashboard_ok = True
    if mode == "live":
        if not _secret_present("DASHBOARD_ADMIN_KEY", op_fields=op_fields):
            errors.append("Missing `DASHBOARD_ADMIN_KEY` in live mode.")
            dashboard_ok = False
        if not _secret_present("DASHBOARD_SESSION_SECRET", op_fields=op_fields):
            errors.append("Missing `DASHBOARD_SESSION_SECRET` in live mode.")
            dashboard_ok = False
        if not _secret_present("DASHBOARD_ADMIN_PASSWORD_HASH", op_fields=op_fields):
            errors.append("Missing `DASHBOARD_ADMIN_PASSWORD_HASH` in live mode.")
            dashboard_ok = False
    read_auth_ok = bool(cfg.dashboard.require_api_key_for_reads)
    if not cfg.dashboard.require_api_key_for_reads:
        warnings.append("`dashboard.require_api_key_for_reads` is false; enable it for unattended operation.")

    # Trade/risk envelope
    risk_ok = True
    if cfg.risk.max_risk_per_trade > 0.02:
        msg = (
            f"`risk.max_risk_per_trade={cfg.risk.max_risk_per_trade}` too high for unattended mode "
            "(hard limit <= 0.02)."
        )
        (errors if live_checks else warnings).append(msg)
        if live_checks:
            risk_ok = False
    elif cfg.risk.max_risk_per_trade > 0.01:
        warnings.append(
            f"`risk.max_risk_per_trade={cfg.risk.max_risk_per_trade}` is aggressive "
            "(recommended <= 0.01 for conservative unattended mode)."
        )
    if cfg.trading.max_trades_per_hour <= 0:
        msg = "`trading.max_trades_per_hour` must be > 0 to prevent runaway entry loops."
        (errors if live_checks else warnings).append(msg)
        if live_checks:
            risk_ok = False
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
    stocks_ok = True
    if cfg.stocks.enabled:
        if cfg.stocks.min_hold_days < 1:
            errors.append("`stocks.min_hold_days` must be >= 1 for swing mode.")
            stocks_ok = False
        if cfg.stocks.max_hold_days < cfg.stocks.min_hold_days:
            errors.append("`stocks.max_hold_days` must be >= `stocks.min_hold_days`.")
            stocks_ok = False
        if cfg.stocks.max_hold_days > 30:
            warnings.append("`stocks.max_hold_days` is high; current pilot target is <= 7 days.")
        if mode == "live":
            if not _secret_present("POLYGON_API_KEY", op_fields=op_fields):
                errors.append("Stocks enabled but Polygon API key is missing (`POLYGON_API_KEY`).")
                stocks_ok = False
            if not _secret_present("ALPACA_API_KEY", op_fields=op_fields, aliases=("ALPACA_KEY",)):
                errors.append("Stocks enabled but Alpaca API key is missing (`ALPACA_API_KEY`).")
                stocks_ok = False
            if not _secret_present("ALPACA_API_SECRET", op_fields=op_fields, aliases=("ALPACA_SECRET", "ALPACA_SECRET_KEY")):
                errors.append("Stocks enabled but Alpaca API secret is missing (`ALPACA_API_SECRET`).")
                stocks_ok = False

    # Circuit breakers
    mon = cfg.monitoring
    breakers_ok = True
    if not mon.auto_pause_on_stale_data:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_stale_data` must be true.")
        if live_checks:
            breakers_ok = False
    if not mon.auto_pause_on_ws_disconnect:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_ws_disconnect` must be true.")
        if live_checks:
            breakers_ok = False
    if not mon.auto_pause_on_consecutive_losses:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_consecutive_losses` must be true.")
        if live_checks:
            breakers_ok = False
    if mon.consecutive_losses_pause_threshold > 5:
        warnings.append(
            f"`monitoring.consecutive_losses_pause_threshold={mon.consecutive_losses_pause_threshold}` is high."
        )
    if not mon.auto_pause_on_drawdown:
        (errors if live_checks else warnings).append("`monitoring.auto_pause_on_drawdown` must be true.")
        if live_checks:
            breakers_ok = False
    if mon.drawdown_pause_pct > 10.0:
        warnings.append(f"`monitoring.drawdown_pause_pct={mon.drawdown_pause_pct}` is high for unattended mode.")

    # DB path sanity
    db_ok = True
    db_path = Path(cfg.app.db_path)
    db_parent = db_path.parent if db_path.parent else Path(".")
    try:
        db_parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Cannot create DB directory `{db_parent}`: {e}")
        db_ok = False
    if str(cfg.app.db_path).strip() in (":memory:", ""):
        errors.append("`app.db_path` must be a persistent file path (not `:memory:`).")
        db_ok = False

    # Optional ES pipeline checks
    es_ok = True
    if cfg.elasticsearch.enabled:
        has_cloud = bool(cfg.elasticsearch.cloud_id.strip())
        has_hosts = bool(cfg.elasticsearch.hosts)
        if not (has_cloud or has_hosts):
            errors.append("Elasticsearch enabled but no `cloud_id` or `hosts` configured.")
            es_ok = False
        if not _secret_present("ES_API_KEY", op_fields=op_fields):
            errors.append("Elasticsearch enabled but no API key configured (`ES_API_KEY` or config value).")
            es_ok = False
        if not _secret_present("COINGECKO_API_KEY", op_fields=op_fields):
            warnings.append(
                "Elasticsearch enrichment is enabled without `COINGECKO_API_KEY`; "
                "market-data enrichment coverage may be reduced."
            )

    # Stripe/Billing readiness
    stripe_enabled = bool(cfg.billing.stripe.enabled)
    stripe_has_basics = all(
        _secret_present(name, op_fields=op_fields)
        for name in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_RESTRICTED_KEY")
    )
    stripe_has_runtime = all(
        _secret_present(name, op_fields=op_fields)
        for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")
    )
    stripe_has_price = any(
        _secret_present(name, op_fields=op_fields)
        for name in ("STRIPE_PRICE_ID", "STRIPE_PRICE_ID_PRO", "STRIPE_PRICE_ID_PREMIUM")
    )
    if stripe_enabled and not stripe_has_runtime:
        errors.append(
            "Stripe is enabled but runtime billing fields are incomplete "
            "(`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`)."
        )
    if stripe_enabled and not stripe_has_price:
        errors.append(
            "Stripe is enabled but no paid price id is configured "
            "(`STRIPE_PRICE_ID` or `STRIPE_PRICE_ID_PRO` or `STRIPE_PRICE_ID_PREMIUM`)."
        )
    elif stripe_has_basics and (not stripe_has_runtime or not stripe_has_price):
        warnings.append(
            "Stripe base keys detected, but checkout runtime fields are incomplete "
            "(`STRIPE_WEBHOOK_SECRET` and at least one price id)."
        )

    # Signal webhook readiness
    signal_webhooks_enabled = bool(cfg.webhooks.enabled)
    if signal_webhooks_enabled and not _secret_present("SIGNAL_WEBHOOK_SECRET", op_fields=op_fields):
        errors.append(
            "Signal webhooks are enabled but `SIGNAL_WEBHOOK_SECRET` is missing."
        )
    if signal_webhooks_enabled and not (cfg.webhooks.allowed_sources or []):
        warnings.append(
            "Signal webhooks are enabled with empty `webhooks.allowed_sources`; "
            "set an allowlist for provider/source pinning."
        )

    # Secret source readiness
    secrets_ok = True
    if any(_is_op_reference(_env(k)) for k in os.environ.keys()) and not op_fields:
        warnings.append(
            "Detected `op://` references but 1Password field inventory is unavailable. "
            "Ensure runtime secret injection is configured."
        )
        secrets_ok = False

    if _env("OP_SERVICE_ACCOUNT_TOKEN"):
        wanted_vaults = [v.strip() for v in _env("OP_VAULTS").split(",") if v.strip()]
        if len(wanted_vaults) == 1:
            warnings.append(
                f"1Password is scoped to one vault (`{wanted_vaults[0]}`); "
                "confirm item-level ACLs for trading/dashboard/billing/data separation."
            )

    pilot_score, scale_score, checks = _compute_readiness_scores(
        mode_ok=mode_ok,
        exchange_ok=exchange_ok,
        dashboard_ok=dashboard_ok,
        risk_ok=risk_ok,
        breakers_ok=breakers_ok,
        db_ok=db_ok,
        read_auth_ok=read_auth_ok,
        secrets_ok=secrets_ok,
        stocks_ok=stocks_ok,
        es_ok=es_ok,
        cfg=cfg,
        account_specs=account_specs,
        op_fields=op_fields,
    )

    print("NovaPulse Live Preflight")
    print(
        f"mode={cfg.app.mode} exchanges={','.join(exchange_names)} accounts={len(account_specs)} "
        f"canary={cfg.trading.canary_mode} stocks={cfg.stocks.enabled}"
    )
    print(f"readiness: pilot={pilot_score}/10 scale={scale_score}/10")
    if errors:
        print("\nFAILURES:")
        for item in errors:
            print(f" - {item}")
    if warnings:
        print("\nWARNINGS:")
        for item in warnings:
            print(f" - {item}")

    if min_pilot_score is not None and pilot_score < int(min_pilot_score):
        errors.append(
            f"Pilot readiness score {pilot_score}/10 below target {int(min_pilot_score)}/10."
        )
    if min_scale_score is not None and scale_score < int(min_scale_score):
        errors.append(
            f"Scale readiness score {scale_score}/10 below target {int(min_scale_score)}/10."
        )

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
    parser.add_argument(
        "--min-pilot-score",
        type=int,
        default=None,
        help="Fail if computed pilot readiness score is below this value.",
    )
    parser.add_argument(
        "--min-scale-score",
        type=int,
        default=None,
        help="Fail if computed scale readiness score is below this value.",
    )
    args = parser.parse_args()
    raise SystemExit(
        run_preflight(
            require_live=not args.allow_paper,
            strict=args.strict,
            min_pilot_score=args.min_pilot_score,
            min_scale_score=args.min_scale_score,
        )
    )


if __name__ == "__main__":
    main()
