"""
Multi-exchange orchestration helpers.

Keeps the main app single-process while running multiple BotEngine
instances (one per exchange) and presenting a unified dashboard/control
surface.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.control_router import ControlRouter


class MultiControlRouter:
    """Fan-out control router for multiple engines."""

    def __init__(self, routers: List[Optional[ControlRouter]]) -> None:
        self._routers = [r for r in routers if r]

    def _target_routers(self, tenant_id: Optional[str]) -> List[ControlRouter]:
        if tenant_id is None:
            return self._routers
        targets: List[ControlRouter] = []
        for router in self._routers:
            engine = getattr(router, "_engine", None)
            if str(getattr(engine, "tenant_id", "")) == str(tenant_id):
                targets.append(router)
        return targets

    async def pause(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        targets = self._target_routers(tenant_id)
        if not targets:
            return {"ok": False, "error": "no routers configured"}
        results = await asyncio.gather(*(r.pause(tenant_id=tenant_id) for r in targets), return_exceptions=True)
        ok = all(isinstance(r, dict) and r.get("ok") for r in results)
        return {"ok": ok, "status": "paused"}

    async def resume(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        targets = self._target_routers(tenant_id)
        if not targets:
            return {"ok": False, "error": "no routers configured"}
        results = await asyncio.gather(*(r.resume(tenant_id=tenant_id) for r in targets), return_exceptions=True)
        ok = all(isinstance(r, dict) and r.get("ok") for r in results)
        return {"ok": ok, "status": "resumed"}

    async def close_all(self, reason: str = "control", tenant_id: Optional[str] = None) -> Dict[str, Any]:
        targets = self._target_routers(tenant_id)
        if not targets:
            return {"ok": False, "error": "no routers configured", "closed": 0}
        results = await asyncio.gather(
            *(r.close_all(reason, tenant_id=tenant_id) for r in targets),
            return_exceptions=True,
        )
        closed = 0
        ok = True
        for r in results:
            if isinstance(r, dict):
                closed += int(r.get("closed", 0) or 0)
                ok = ok and bool(r.get("ok", False))
            else:
                ok = False
        return {"ok": ok, "closed": closed}

    async def kill(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        targets = self._target_routers(tenant_id)
        if not targets:
            return {"ok": False, "error": "no routers configured"}
        results = await asyncio.gather(*(r.kill(tenant_id=tenant_id) for r in targets), return_exceptions=True)
        ok = all(isinstance(r, dict) and r.get("ok") for r in results)
        closed = sum(int(r.get("closed", 0) or 0) for r in results if isinstance(r, dict))
        return {"ok": ok, "closed": closed}


class MultiEngineHub:
    """Lightweight hub object for DashboardServer multi-engine support."""

    def __init__(self, engines: List[Any]) -> None:
        self.engines = engines
        primary = engines[0] if engines else None
        self.config = getattr(primary, "config", None)
        self.db = getattr(primary, "db", None)


def resolve_exchange_names(default: Optional[str] = None) -> List[str]:
    raw = os.getenv("TRADING_EXCHANGES") or os.getenv("TRADING_EXCHANGE") or ""
    names: List[str] = []
    if raw:
        names = [p.strip().lower() for p in raw.split(",") if p.strip()]
    else:
        fallback = os.getenv("ACTIVE_EXCHANGE") or os.getenv("EXCHANGE_NAME") or (default or "")
        if fallback:
            names = [fallback.strip().lower()]
    # De-duplicate while preserving order
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def resolve_trading_accounts(
    default_exchange: Optional[str] = None,
    config_accounts: str = "",
) -> List[Dict[str, str]]:
    """
    Resolve account/exchange specs from env/config.

    Format:
    - `TRADING_ACCOUNTS=main:kraken,main:coinbase,swing:kraken`
    - falls back to exchange-only mode with account_id=default
    """
    raw = (os.getenv("TRADING_ACCOUNTS") or config_accounts or "").strip()
    specs: List[Dict[str, str]] = []
    if raw:
        for token in raw.split(","):
            item = token.strip()
            if not item:
                continue
            if ":" in item:
                account_id, exchange = item.split(":", 1)
                acc = (account_id or "default").strip().lower()
                ex = (exchange or default_exchange or "kraken").strip().lower()
            else:
                acc = "default"
                ex = item.strip().lower() or (default_exchange or "kraken")
            specs.append({"account_id": acc, "exchange": ex})
    else:
        exchanges = resolve_exchange_names(default_exchange)
        specs = [{"account_id": "default", "exchange": ex} for ex in exchanges]

    # Stable de-duplication
    deduped: List[Dict[str, str]] = []
    seen = set()
    for spec in specs:
        key = (spec["account_id"], spec["exchange"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def resolve_db_path(base_path: str, exchange: str, multi: bool, account_id: str = "") -> str:
    if not base_path:
        base_path = "data/trading.db"
    account = "".join(ch if ch.isalnum() else "_" for ch in (account_id or "").lower()).strip("_")
    if not multi and not account:
        return base_path

    exchange_key = "".join(ch if ch.isalnum() else "_" for ch in exchange.lower())
    if "{exchange}" in base_path:
        db_path = base_path.format(exchange=exchange_key)
    else:
        path = Path(base_path)
        stem = path.stem or "trading"
        suffix = path.suffix or ".db"
        db_path = str(path.with_name(f"{stem}_{exchange_key}{suffix}"))

    if account:
        p = Path(db_path)
        stem = p.stem or "trading"
        suffix = p.suffix or ".db"
        db_path = str(p.with_name(f"{stem}_{account}{suffix}"))
    return db_path
