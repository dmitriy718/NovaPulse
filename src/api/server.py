"""
FastAPI Dashboard Server - REST + WebSocket API for monitoring and control.

Provides real-time dashboard data, trade management endpoints,
WebSocket streaming for live updates, and system control commands.

# ENHANCEMENT: Added CORS and security middleware
# ENHANCEMENT: Added request rate limiting
# ENHANCEMENT: Added WebSocket heartbeat for stale connection detection
# ENHANCEMENT: Added API versioning support
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import html
import io
import json
import os
import time
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import (
    Body,
    Cookie,
    Depends,
    FastAPI,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.core.logger import get_logger

logger = get_logger("api_server")


class DashboardServer:
    """
    FastAPI-based dashboard server with WebSocket streaming.
    
    Endpoints:
    - GET /api/v1/status - System status
    - GET /api/v1/trades - Trade history
    - GET /api/v1/positions - Open positions
    - GET /api/v1/performance - Performance metrics
    - GET /api/v1/strategies - Strategy stats
    - GET /api/v1/risk - Risk report
    - GET /api/v1/thoughts - AI thought feed
    - GET /api/v1/scanner - Market scanner results
    - POST /api/v1/control/close_all - Emergency close all
    - POST /api/v1/control/pause - Pause trading
    - POST /api/v1/control/resume - Resume trading
    - WS /ws/live - Real-time data stream
    
    # ENHANCEMENT: Added response caching for frequently accessed data
    # ENHANCEMENT: Added WebSocket binary protocol for efficiency
    """

    def __init__(self):
        self.app = FastAPI(
            title="NovaPulse Command Center",
            version=__version__,
            docs_url="/api/docs",
        )
        # Control plane auth:
        # - Cookie session (web UI)
        # - API keys (CLI/automation): separate read vs admin
        # Backward compatibility:
        # - DASHBOARD_SECRET_KEY (legacy) -> DASHBOARD_ADMIN_KEY
        # - DASHBOARD_READONLY_KEY (legacy) -> DASHBOARD_READ_KEY
        self._admin_key = (
            os.getenv("DASHBOARD_ADMIN_KEY")
            or os.getenv("DASHBOARD_SECRET_KEY")
            or ""
        ).strip()
        self._read_key = (
            os.getenv("DASHBOARD_READ_KEY")
            or os.getenv("DASHBOARD_READONLY_KEY")
            or ""
        ).strip()
        self._generated_admin_key = False
        if not self._admin_key:
            self._admin_key = secrets.token_urlsafe(32)
            self._generated_admin_key = True

        self._session_secret = os.getenv("DASHBOARD_SESSION_SECRET", "").strip()
        self._generated_session_secret = False
        if not self._session_secret:
            self._session_secret = secrets.token_urlsafe(48)
            self._generated_session_secret = True

        self._admin_username = (os.getenv("DASHBOARD_ADMIN_USERNAME", "admin") or "admin").strip()
        self._admin_password = (os.getenv("DASHBOARD_ADMIN_PASSWORD", "") or "").strip()
        self._admin_password_hash = (os.getenv("DASHBOARD_ADMIN_PASSWORD_HASH", "") or "").strip()
        self._session_cookie = "np_session"
        self._csrf_cookie = "np_csrf"
        self._session_ttl_seconds = int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "43200") or "43200")

        # Lazy init in case optional deps are removed in some deployments.
        self._session_serializer = None
        self._password_hasher = None
        self._setup_middleware()
        self._setup_routes()
        self._ws_connections: Set[WebSocket] = set()
        self._bot_engine = None
        self._control_router = None
        self._stripe_service = None
        self._ws_cache_by_tenant: Dict[str, Dict[str, Any]] = {}
        self._ws_cache_time_by_tenant: Dict[str, float] = {}

    def set_bot_engine(self, engine) -> None:
        """Inject the bot engine reference."""
        self._bot_engine = engine
        if engine and getattr(engine, "config", None):
            if engine.config.app.mode == "live" and self._generated_admin_key:
                raise RuntimeError(
                    "DASHBOARD_ADMIN_KEY is required in live mode."
                )
            if engine.config.app.mode == "live" and self._generated_session_secret:
                raise RuntimeError("DASHBOARD_SESSION_SECRET is required in live mode.")

            if engine.config.app.mode == "live" and not self._admin_password_hash:
                raise RuntimeError("DASHBOARD_ADMIN_PASSWORD_HASH is required in live mode.")

            if self._generated_admin_key:
                logger.warning(
                    "DASHBOARD_ADMIN_KEY not set; generated an ephemeral key. "
                    "Set the env var to enable admin control endpoints across restarts.",
                )
            if self._generated_session_secret:
                logger.warning(
                    "DASHBOARD_SESSION_SECRET not set; generated an ephemeral secret. "
                    "Set the env var to keep web sessions valid across restarts.",
                )
        if self._stripe_service and engine and getattr(engine, "db", None):
            self._stripe_service.set_db(engine.db)

    def set_control_router(self, router) -> None:
        """Inject the control router for pause/resume/close_all."""
        self._control_router = router

    def set_stripe_service(self, service) -> None:
        """Inject Stripe service for billing endpoints."""
        self._stripe_service = service
        if self._bot_engine and getattr(self._bot_engine, "db", None):
            service.set_db(self._bot_engine.db)

    async def resolve_tenant_id(
        self,
        requested_tenant_id: str = "",
        api_key: str = "",
        *,
        require_api_key: bool = False,
    ) -> str:
        """
        Resolve tenant_id from user-provided inputs (headers/query) with defense-in-depth.

        Rules:
        - Dashboard secret key is admin-level: may target any tenant explicitly.
        - Tenant API keys are pinned: requested tenant must match mapping.
        - If tenant is inactive (not active/trialing), deny non-admin access.
        - If no valid mapping exists, never trust arbitrary tenant IDs; use default tenant.
        """
        requested_tenant_id = (requested_tenant_id or "").strip()
        api_key = (api_key or "").strip()

        if require_api_key and not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")

        primary = self._get_primary_engine()
        default_tenant_id = (
            primary.config.billing.tenant.default_tenant_id
            if primary and getattr(primary, "config", None)
            else "default"
        )

        # Admin/read keys may explicitly target any tenant (control endpoints still require admin).
        if api_key and (api_key == self._admin_key or (self._read_key and api_key == self._read_key)):
            return requested_tenant_id or default_tenant_id

        primary_db = primary.db if (primary and getattr(primary, "db", None)) else None
        if require_api_key and not primary_db and not self._get_engines():
            # Fail closed if we can't validate keys yet.
            raise HTTPException(status_code=503, detail="Tenant DB unavailable")

        mapped_tenant_id = None
        mapped_db = None
        if api_key:
            for eng in self._get_engines():
                db = getattr(eng, "db", None)
                if not db:
                    continue
                try:
                    candidate = await db.get_tenant_id_by_api_key(api_key)
                except Exception:
                    candidate = None
                if candidate:
                    mapped_tenant_id = candidate
                    mapped_db = db
                    break

        async def _ensure_active(tenant_id: str) -> str:
            dbs: List[Any] = []
            if mapped_db:
                dbs.append(mapped_db)
            if primary_db and primary_db not in dbs:
                dbs.append(primary_db)
            for eng in self._get_engines():
                db = getattr(eng, "db", None)
                if db and db not in dbs:
                    dbs.append(db)
            if not dbs:
                return tenant_id
            for db in dbs:
                try:
                    tenant = await db.get_tenant(tenant_id)
                except Exception:
                    tenant = None
                if tenant:
                    if tenant.get("status") not in ("active", "trialing"):
                        raise HTTPException(status_code=403, detail="Tenant inactive")
                    return tenant_id
            return tenant_id

        if mapped_tenant_id:
            if requested_tenant_id and requested_tenant_id != mapped_tenant_id:
                raise HTTPException(status_code=403, detail="Tenant mismatch for API key")
            return await _ensure_active(mapped_tenant_id)

        if require_api_key and api_key:
            raise HTTPException(status_code=403, detail="Invalid API key")

        return await _ensure_active(default_tenant_id)

    def _get_engines(self) -> List[Any]:
        if not self._bot_engine:
            return []
        engines = getattr(self._bot_engine, "engines", None)
        if engines is not None:
            return [e for e in engines if e]
        return [self._bot_engine]

    def _get_primary_engine(self):
        engines = self._get_engines()
        return engines[0] if engines else None

    def _engines_share_db(self, engines: List[Any]) -> bool:
        paths = []
        for e in engines:
            db = getattr(e, "db", None)
            if db and getattr(db, "db_path", None):
                paths.append(db.db_path)
        return len(set(paths)) <= 1

    def _aggregate_performance_stats(self, stats_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        agg = {
            "total_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "open_positions": 0,
            "today_pnl": 0.0,
        }

        total_wins = 0
        total_losses = 0
        sum_win = 0.0
        sum_loss = 0.0

        for s in stats_list:
            if not s:
                continue
            agg["total_pnl"] += float(s.get("total_pnl", 0.0) or 0.0)
            agg["total_trades"] += int(s.get("total_trades", 0) or 0)
            wins = int(s.get("winning_trades", 0) or 0)
            losses = int(s.get("losing_trades", 0) or 0)
            agg["winning_trades"] += wins
            agg["losing_trades"] += losses
            agg["open_positions"] += int(s.get("open_positions", 0) or 0)
            agg["today_pnl"] += float(s.get("today_pnl", 0.0) or 0.0)

            if wins > 0:
                sum_win += float(s.get("avg_win", 0.0) or 0.0) * wins
                total_wins += wins
            if losses > 0:
                sum_loss += float(s.get("avg_loss", 0.0) or 0.0) * losses
                total_losses += losses

        if agg["total_trades"] > 0:
            agg["win_rate"] = agg["winning_trades"] / agg["total_trades"]
        if total_wins > 0:
            agg["avg_win"] = sum_win / total_wins
        if total_losses > 0:
            agg["avg_loss"] = sum_loss / total_losses

        # Multi-engine note: use weighted average by realized trade count rather than
        # passing through the first engine's risk ratios.
        risk_rows: List[Tuple[float, float, int]] = []
        for s in stats_list:
            if not s:
                continue
            try:
                sharpe = float(s.get("sharpe_ratio", 0.0) or 0.0)
                sortino = float(s.get("sortino_ratio", 0.0) or 0.0)
                trades = int(s.get("total_trades", 0) or 0)
                if trades > 0:
                    risk_rows.append((sharpe, sortino, trades))
            except Exception:
                continue
        if risk_rows:
            total_weight = sum(max(r[2], 1) for r in risk_rows)
            agg["sharpe_ratio"] = sum(r[0] * max(r[2], 1) for r in risk_rows) / total_weight
            agg["sortino_ratio"] = sum(r[1] * max(r[2], 1) for r in risk_rows) / total_weight

        return agg

    def _aggregate_risk_reports(self, reports: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not reports:
            return {}

        bankroll = sum(float(r.get("bankroll", 0.0) or 0.0) for r in reports)
        initial_bankroll = sum(float(r.get("initial_bankroll", 0.0) or 0.0) for r in reports)
        peak_bankroll = sum(float(r.get("peak_bankroll", 0.0) or 0.0) for r in reports)
        daily_pnl = sum(float(r.get("daily_pnl", 0.0) or 0.0) for r in reports)
        daily_trades = sum(int(r.get("daily_trades", 0) or 0) for r in reports)
        open_positions = sum(int(r.get("open_positions", 0) or 0) for r in reports)
        total_exposure = sum(float(r.get("total_exposure_usd", 0.0) or 0.0) for r in reports)
        remaining_capacity = sum(float(r.get("remaining_capacity_usd", 0.0) or 0.0) for r in reports)
        trade_count = sum(int(r.get("trade_count", 0) or 0) for r in reports)

        max_drawdown_pct = max(float(r.get("max_drawdown_pct", 0.0) or 0.0) for r in reports)
        risk_of_ruin_vals = [float(r.get("risk_of_ruin", 0.0) or 0.0) for r in reports]
        drawdown_factors = [float(r.get("drawdown_factor", 1.0) or 1.0) for r in reports]

        if peak_bankroll > 0:
            current_drawdown = (peak_bankroll - bankroll) / peak_bankroll * 100
        else:
            current_drawdown = 0.0

        if bankroll > 0:
            weighted_ror = sum(
                risk_of_ruin_vals[i] * float(reports[i].get("bankroll", 0.0) or 0.0)
                for i in range(len(reports))
            ) / bankroll
            weighted_df = sum(
                drawdown_factors[i] * float(reports[i].get("bankroll", 0.0) or 0.0)
                for i in range(len(reports))
            ) / bankroll
        else:
            weighted_ror = max(risk_of_ruin_vals) if risk_of_ruin_vals else 0.0
            weighted_df = max(drawdown_factors) if drawdown_factors else 1.0

        total_return_pct = ((bankroll - initial_bankroll) / initial_bankroll * 100) if initial_bankroll > 0 else 0.0

        return {
            "bankroll": round(bankroll, 2),
            "initial_bankroll": round(initial_bankroll, 2),
            "total_return_pct": round(total_return_pct, 2),
            "peak_bankroll": round(peak_bankroll, 2),
            "current_drawdown": round(current_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_trades": daily_trades,
            "open_positions": open_positions,
            "total_exposure_usd": round(total_exposure, 2),
            "risk_of_ruin": round(weighted_ror, 4),
            "drawdown_factor": round(weighted_df, 2),
            "remaining_capacity_usd": round(remaining_capacity, 2),
            "trade_count": trade_count,
        }

    @staticmethod
    def _normalize_chart_timeframe(value: str) -> str:
        raw = (value or "").strip().lower()
        aliases = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "1hr": "1h",
            "1hour": "1h",
            "60m": "1h",
            "1d": "1d",
            "1day": "1d",
            "24h": "1d",
        }
        return aliases.get(raw, "5m")

    @staticmethod
    def _chart_tf_seconds(tf: str) -> int:
        return {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "1d": 86400,
        }.get(tf, 300)

    @staticmethod
    def _chart_tf_minutes(tf: str) -> int:
        return {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "1d": 1440,
        }.get(tf, 5)

    @staticmethod
    def _split_exchange_account(exchange: str = "", account_id: str = "") -> Tuple[str, str]:
        ex = (exchange or "").strip().lower()
        acct = (account_id or "").strip().lower()
        if ":" in ex and not acct:
            left, right = ex.split(":", 1)
            ex = left.strip().lower()
            acct = right.strip().lower()
        return ex, acct

    def _resolve_chart_engine(
        self,
        pair: str,
        exchange: str = "",
        account_id: str = "",
    ) -> Optional[Any]:
        engines = self._get_engines()
        if not engines:
            return None

        p = (pair or "").strip()
        ex, acct = self._split_exchange_account(exchange, account_id)

        def _matches_scope(eng: Any) -> bool:
            eng_ex = str(getattr(eng, "exchange_name", "")).strip().lower()
            eng_acct = str(getattr(eng, "tenant_id", "default")).strip().lower()
            if ex and eng_ex != ex:
                return False
            if acct and eng_acct != acct:
                return False
            return True

        if ex or acct:
            for eng in engines:
                if _matches_scope(eng) and (not p or p in (getattr(eng, "pairs", []) or [])):
                    return eng
            for eng in engines:
                if _matches_scope(eng):
                    return eng

        if p:
            for eng in engines:
                if p in (getattr(eng, "pairs", []) or []):
                    return eng

        return engines[0]

    @staticmethod
    def _resolve_backtest_friction(engine: Any, body: Dict[str, Any]) -> Tuple[float, float]:
        """
        Resolve backtest friction knobs.

        - `fee_pct` defaults to exchange taker fee.
        - `slippage_pct` defaults to 0.1% unless explicitly provided.
        """
        exch = getattr(getattr(engine, "config", None), "exchange", None)
        fee_default = float(getattr(exch, "taker_fee", 0.0026) or 0.0026)
        fee_pct = max(0.0, float(body.get("fee_pct", fee_default) or fee_default))
        slippage_pct = max(0.0, float(body.get("slippage_pct", 0.001) or 0.001))
        return slippage_pct, fee_pct

    def _aggregate_cached_bars(
        self,
        *,
        times: List[float],
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
        timeframe_seconds: int,
        limit: int,
    ) -> List[Dict[str, float]]:
        if not times:
            return []

        step = max(60, int(timeframe_seconds))
        out: List[Dict[str, float]] = []
        cur_bucket: Optional[int] = None
        cur: Optional[Dict[str, float]] = None

        for idx, ts in enumerate(times):
            try:
                t = float(ts)
                o = float(opens[idx])
                h = float(highs[idx])
                l = float(lows[idx])
                c = float(closes[idx])
                v = float(volumes[idx])
            except (TypeError, ValueError, IndexError):
                continue

            if t <= 0:
                continue
            bucket = int(t // step) * step
            if cur_bucket is None or bucket != cur_bucket:
                if cur is not None:
                    out.append(cur)
                cur_bucket = bucket
                cur = {
                    "time": float(bucket),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": max(0.0, v),
                }
                continue

            if cur is None:
                continue
            cur["high"] = max(cur["high"], h)
            cur["low"] = min(cur["low"], l)
            cur["close"] = c
            cur["volume"] += max(0.0, v)

        if cur is not None:
            out.append(cur)
        if len(out) > limit:
            return out[-limit:]
        return out

    async def _get_crypto_chart_bars(
        self,
        engine: Any,
        *,
        pair: str,
        timeframe: str,
        limit: int,
    ) -> Tuple[List[Dict[str, float]], str]:
        # Prefer exchange REST candles for charting so higher timeframes
        # have sufficient depth even when the in-memory 1m cache is short.
        rest_bars = await self._get_crypto_chart_bars_rest(
            engine,
            pair=pair,
            timeframe=timeframe,
            limit=limit,
        )
        if rest_bars:
            return rest_bars, "rest"

        cache_bars = self._get_crypto_chart_bars_from_cache(
            engine,
            pair=pair,
            timeframe=timeframe,
            limit=limit,
        )
        return cache_bars, "cache"

    async def _get_crypto_chart_bars_rest(
        self,
        engine: Any,
        *,
        pair: str,
        timeframe: str,
        limit: int,
    ) -> List[Dict[str, float]]:
        rest = getattr(engine, "rest_client", None)
        if rest is None or not hasattr(rest, "get_ohlc"):
            return []

        interval_minutes = self._chart_tf_minutes(timeframe)
        # Add a small buffer so indicators still look stable after filtering.
        target_bars = max(int(limit) + 20, 80)
        since_ts = int(time.time()) - (interval_minutes * 60 * target_bars)

        try:
            rows = await rest.get_ohlc(pair, interval=interval_minutes, since=since_ts)
        except Exception:
            return []

        if not isinstance(rows, list) or not rows:
            return []

        bars_by_bucket: Dict[int, Dict[str, float]] = {}
        for row in rows:
            try:
                if isinstance(row, dict):
                    t = float(row.get("time", 0) or 0)
                    o = float(row.get("open", 0) or 0)
                    h = float(row.get("high", 0) or 0)
                    l = float(row.get("low", 0) or 0)
                    c = float(row.get("close", 0) or 0)
                    v = float(row.get("volume", 0) or 0)
                else:
                    t = float(row[0])
                    o = float(row[1])
                    h = float(row[2])
                    l = float(row[3])
                    c = float(row[4])
                    # Kraken/Coinbase normalized shape: [time, open, high, low, close, vwap, volume, count]
                    v = float(row[6]) if len(row) > 6 else 0.0
            except (TypeError, ValueError, IndexError):
                continue

            if t <= 0 or o <= 0 or h <= 0 or l <= 0 or c <= 0:
                continue

            bucket = int(t // (interval_minutes * 60)) * (interval_minutes * 60)
            bars_by_bucket[bucket] = {
                "time": float(bucket),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": max(0.0, v),
            }

        if not bars_by_bucket:
            return []

        ordered = [bars_by_bucket[k] for k in sorted(bars_by_bucket.keys())]
        return ordered[-int(limit):]

    def _get_crypto_chart_bars_from_cache(
        self,
        engine: Any,
        *,
        pair: str,
        timeframe: str,
        limit: int,
    ) -> List[Dict[str, float]]:
        md = getattr(engine, "market_data", None)
        if md is None:
            return []

        tf_sec = self._chart_tf_seconds(timeframe)
        ratio = max(1, int(tf_sec // 60))
        fetch_n = max(int(limit) * ratio * 2, int(limit) * ratio + 20, 300)

        times = list(md.get_times(pair, fetch_n))
        opens = list(md.get_opens(pair, fetch_n))
        highs = list(md.get_highs(pair, fetch_n))
        lows = list(md.get_lows(pair, fetch_n))
        closes = list(md.get_closes(pair, fetch_n))
        volumes = list(md.get_volumes(pair, fetch_n))
        if not times:
            return []

        if timeframe == "1m":
            raw = []
            n = min(len(times), len(opens), len(highs), len(lows), len(closes), len(volumes))
            start = max(0, n - int(limit))
            for i in range(start, n):
                try:
                    raw.append(
                        {
                            "time": float(times[i]),
                            "open": float(opens[i]),
                            "high": float(highs[i]),
                            "low": float(lows[i]),
                            "close": float(closes[i]),
                            "volume": float(volumes[i]),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            return raw

        return self._aggregate_cached_bars(
            times=times,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            timeframe_seconds=tf_sec,
            limit=int(limit),
        )

    async def _get_stock_chart_bars(
        self,
        engine: Any,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> List[Dict[str, float]]:
        polygon = getattr(engine, "polygon", None)
        if not polygon:
            return []

        tf_map: Dict[str, Tuple[int, str]] = {
            "1m": (1, "minute"),
            "5m": (5, "minute"),
            "15m": (15, "minute"),
            "30m": (30, "minute"),
            "1h": (1, "hour"),
            "1d": (1, "day"),
        }
        mult, span = tf_map.get(timeframe, (5, "minute"))
        return await polygon.get_aggregate_bars(
            symbol=symbol,
            multiplier=mult,
            timespan=span,
            limit=int(limit),
        )

    @staticmethod
    def _candles_to_dataframe(candles: List[Dict[str, Any]]):
        """Convert normalized OHLCV candle dicts to a pandas DataFrame."""
        import pandas as pd

        rows = []
        for c in candles:
            try:
                rows.append(
                    {
                        "time": float(c.get("time", 0) or 0),
                        "open": float(c.get("open", 0) or 0),
                        "high": float(c.get("high", 0) or 0),
                        "low": float(c.get("low", 0) or 0),
                        "close": float(c.get("close", 0) or 0),
                        "volume": float(c.get("volume", 0) or 0),
                    }
                )
            except Exception:
                continue
        if not rows:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows)
        df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last")
        return df.reset_index(drop=True)

    @staticmethod
    def _verify_signal_signature(
        payload: bytes,
        signature_header: str,
        *,
        secret: str,
        timestamp: str = "",
        max_skew_seconds: int = 300,
    ) -> bool:
        """
        Verify HMAC SHA256 signature for signal webhooks.

        Signature format accepted:
        - plain hex digest: sha256(payload)
        - `t=<ts>,v1=<hex>` style (Stripe-like)
        """
        if not secret:
            return False
        provided = (signature_header or "").strip()
        if not provided:
            return False

        ts = (timestamp or "").strip()
        if provided.startswith("t="):
            parts = {}
            for token in provided.split(","):
                if "=" in token:
                    k, v = token.split("=", 1)
                    parts[k.strip()] = v.strip()
            ts = parts.get("t", ts)
            provided = parts.get("v1", "")

        if not provided:
            return False

        if ts:
            try:
                now = int(time.time())
                tsv = int(float(ts))
                if abs(now - tsv) > max(1, int(max_skew_seconds)):
                    return False
                signed_payload = f"{ts}.{payload.decode('utf-8')}".encode("utf-8")
            except Exception:
                return False
        else:
            signed_payload = payload

        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    def _setup_middleware(self) -> None:
        """Configure CORS and security middleware."""
        def _norm_origin(origin: str) -> str:
            return (origin or "").strip().rstrip("/")

        # Restrict CORS by default; allow explicit overrides via env.
        origins_env = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
        public_origin = _norm_origin(
            os.getenv("DASHBOARD_PUBLIC_ORIGIN", "https://nova.horizonsvc.com")
        )
        if origins_env:
            allow_origins = [_norm_origin(o) for o in origins_env.split(",") if _norm_origin(o)]
        else:
            # Include both container port and host-mapped port so the
            # browser Origin header matches regardless of Docker mapping.
            container_port = os.getenv("DASHBOARD_PORT", "8080")
            allow_origins = [
                f"http://localhost:{container_port}",
                f"http://127.0.0.1:{container_port}",
            ]
            host_port_env = (os.getenv("HOST_PORT", "") or "").strip()
            if host_port_env:
                # HOST_PORT may include bind address, e.g. "127.0.0.1:8090"
                hp = host_port_env.rsplit(":", 1)[-1] if ":" in host_port_env else host_port_env
                if hp != container_port:
                    allow_origins.extend([
                        f"http://localhost:{hp}",
                        f"http://127.0.0.1:{hp}",
                    ])

        if public_origin and public_origin not in allow_origins:
            allow_origins.append(public_origin)

        # Store for reuse in CSRF origin check.
        self._allowed_origins: set[str] = set(allow_origins)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["*"],
        )

        # Basic security headers for browser-based operator UI.
        @self.app.middleware("http")
        async def _security_headers_mw(request: Request, call_next):
            resp = await call_next(request)
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("Referrer-Policy", "no-referrer")
            resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            # CSP is intentionally permissive due to inline handlers in the dashboard HTML.
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "connect-src 'self' ws: wss:; "
                "img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "script-src 'self' 'unsafe-inline'",
            )
            if request.url.path.startswith("/api/"):
                resp.headers.setdefault("Cache-Control", "no-store")
            return resp

        # Lightweight in-memory rate limiter (per-client IP token bucket).
        buckets: Dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_ts)
        _last_eviction: List[float] = [0.0]  # mutable container for closure
        _EVICTION_INTERVAL = 60.0  # seconds between eviction sweeps
        _STALE_AGE = 600.0  # evict entries older than 10 minutes

        @self.app.middleware("http")
        async def _rate_limit_mw(request: Request, call_next):
            path = request.url.path or ""
            if path.startswith("/static/") or path in ("/favicon.ico", "/api/v1/health"):
                return await call_next(request)

            primary = self._get_primary_engine()
            dash = getattr(getattr(primary, "config", None), "dashboard", None) if primary else None
            enabled = bool(getattr(dash, "rate_limit_enabled", False)) if dash is not None else False
            if not enabled:
                return await call_next(request)

            rpm = int(getattr(dash, "rate_limit_requests_per_minute", 240) or 240)
            burst = int(getattr(dash, "rate_limit_burst", 60) or 60)
            if rpm < 1:
                rpm = 1
            if burst < 1:
                burst = 1

            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()

            # Periodic eviction of stale entries to prevent memory leak
            if (now - _last_eviction[0]) > _EVICTION_INTERVAL:
                stale_ips = [
                    k for k, (_, ts) in buckets.items()
                    if (now - ts) > _STALE_AGE
                ]
                for k in stale_ips:
                    del buckets[k]
                _last_eviction[0] = now

            # Cap bucket count to prevent memory exhaustion from many IPs
            if ip not in buckets and len(buckets) >= 10000:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

            tokens, last = buckets.get(ip, (float(burst), now))
            rate = float(rpm) / 60.0
            tokens = min(float(burst), tokens + (now - last) * rate)
            if tokens < 1.0:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
            buckets[ip] = (tokens - 1.0, now)
            return await call_next(request)

    def _setup_routes(self) -> None:
        """Register all API routes."""

        # -----------------------------
        # Auth helpers (cookie session + API keys)
        # -----------------------------

        def _is_prod() -> bool:
            env = (os.getenv("APP_ENV", "") or "").strip().lower()
            return env in ("prod", "production")

        def _require_auth_for_reads() -> bool:
            # Backward compatibility:
            # - DASHBOARD_REQUIRE_API_KEY_FOR_READS (current)
            # - DASHBOARD_REQUIRE_AUTH_FOR_READS (legacy)
            env = (
                os.getenv("DASHBOARD_REQUIRE_API_KEY_FOR_READS", "")
                or os.getenv("DASHBOARD_REQUIRE_AUTH_FOR_READS", "")
                or ""
            ).strip().lower()
            if env in ("1", "true", "yes", "y", "on"):
                return True
            if env in ("0", "false", "no", "n", "off"):
                return False

            primary = self._get_primary_engine()
            if primary and getattr(primary, "config", None):
                dash = getattr(primary.config, "dashboard", None)
                if dash is not None and hasattr(dash, "require_api_key_for_reads"):
                    return bool(getattr(dash, "require_api_key_for_reads"))
                # Conservative fallback: live mode should require auth for reads.
                return getattr(primary.config.app, "mode", "paper") == "live"
            return False

        def _serializer():
            if self._session_serializer is None:
                from itsdangerous import URLSafeTimedSerializer

                self._session_serializer = URLSafeTimedSerializer(
                    self._session_secret, salt="novapulse-session-v1"
                )
            return self._session_serializer

        def _hasher():
            if self._password_hasher is None:
                from argon2 import PasswordHasher

                self._password_hasher = PasswordHasher()
            return self._password_hasher

        def _verify_admin_password(password: str) -> bool:
            password = (password or "").strip()
            if not password:
                return False
            if self._admin_password_hash:
                # docker compose expands '$' from .env unless escaped as '$$'.
                # Normalize here so stored hashes remain valid for verification.
                stored_hash = self._admin_password_hash.replace("$$", "$")
                if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
                    try:
                        import bcrypt
                    except Exception:
                        logger.error("bcrypt hash configured but bcrypt package unavailable")
                        return False
                    try:
                        return bool(
                            bcrypt.checkpw(
                                password.encode("utf-8"),
                                stored_hash.encode("utf-8"),
                            )
                        )
                    except Exception:
                        return False
                try:
                    return bool(_hasher().verify(stored_hash, password))
                except Exception:
                    return False
            # Dev fallback only; disallow plaintext in production.
            if _is_prod():
                return False
            return secrets.compare_digest(password, self._admin_password or "")

        def _load_session_from_request(request: Request) -> Optional[Dict[str, Any]]:
            raw = request.cookies.get(self._session_cookie, "")
            if not raw:
                return None
            try:
                data = _serializer().loads(raw, max_age=self._session_ttl_seconds)
                if not isinstance(data, dict):
                    return None
                if data.get("v") != 1:
                    return None
                if data.get("role") not in ("admin", "read"):
                    return None
                return data
            except Exception:
                return None

        def _issue_session(
            response: Response,
            *,
            role: str,
            tenant_id: str,
        ) -> None:
            session = {"v": 1, "role": role, "tid": tenant_id, "iat": int(time.time())}
            token = _serializer().dumps(session)
            csrf = secrets.token_urlsafe(24)

            # Secure cookie defaults; "secure" is auto-disabled on localhost HTTP.
            response.set_cookie(
                self._session_cookie,
                token,
                httponly=True,
                samesite="strict",
                secure=_is_prod(),
                max_age=self._session_ttl_seconds,
                path="/",
            )
            response.set_cookie(
                self._csrf_cookie,
                csrf,
                httponly=False,
                samesite="strict",
                secure=_is_prod(),
                max_age=self._session_ttl_seconds,
                path="/",
            )

        def _clear_session(response: Response) -> None:
            response.delete_cookie(self._session_cookie, path="/")
            response.delete_cookie(self._csrf_cookie, path="/")

        def _check_csrf(request: Request, header_token: str) -> None:
            header_token = (header_token or "").strip()
            cookie_token = (request.cookies.get(self._csrf_cookie, "") or "").strip()
            if not (header_token and cookie_token and secrets.compare_digest(header_token, cookie_token)):
                raise HTTPException(status_code=403, detail="CSRF check failed")

            # Minimal origin defense-in-depth for browsers.
            origin = (request.headers.get("origin", "") or "").strip()
            if origin and origin not in self._allowed_origins:
                raise HTTPException(status_code=403, detail="Origin not allowed")

        async def _require_read_access(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ) -> Dict[str, Any]:
            sess = _load_session_from_request(request)
            if sess:
                return {"auth": "session", "role": sess.get("role"), "tenant_id": sess.get("tid") or "default"}

            if not _require_auth_for_reads():
                return {"auth": "none", "role": "anon", "tenant_id": _default_tenant_id()}

            api_key = (x_api_key or "").strip()
            if not api_key:
                raise HTTPException(status_code=401, detail="Missing credentials")

            # Global keys
            if api_key == self._admin_key:
                return {"auth": "key", "role": "admin", "tenant_id": _default_tenant_id()}
            if self._read_key and api_key == self._read_key:
                return {"auth": "key", "role": "read", "tenant_id": _default_tenant_id()}

            # Tenant keys (read-only)
            for eng in self._get_engines():
                db = getattr(eng, "db", None)
                if not db:
                    continue
                try:
                    tenant_id = await db.get_tenant_id_by_api_key(api_key)
                except Exception:
                    tenant_id = None
                if tenant_id:
                    return {"auth": "tenant_key", "role": "read", "tenant_id": tenant_id}

            raise HTTPException(status_code=403, detail="Invalid credentials")

        async def _require_control_access(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ) -> Dict[str, Any]:
            # Session-based admin (web UI)
            sess = _load_session_from_request(request)
            if sess and sess.get("role") == "admin":
                _check_csrf(request, x_csrf_token)
                return {"auth": "session", "role": "admin", "tenant_id": sess.get("tid") or _default_tenant_id()}

            # Admin key
            api_key = (x_api_key or "").strip()
            if api_key and api_key == self._admin_key:
                return {"auth": "key", "role": "admin", "tenant_id": _default_tenant_id()}

            # Optional: allow tenant API keys for control endpoints.
            primary = self._get_primary_engine()
            allow_tenant = False
            if primary and getattr(primary, "config", None):
                dash = getattr(primary.config, "dashboard", None)
                allow_tenant = bool(getattr(dash, "allow_tenant_keys_for_control", False))
            if not allow_tenant:
                raise HTTPException(status_code=403, detail="Unauthorized")

            if api_key:
                for eng in self._get_engines():
                    db = getattr(eng, "db", None)
                    if not db:
                        continue
                    try:
                        tenant_id = await db.get_tenant_id_by_api_key(api_key)
                    except Exception:
                        tenant_id = None
                    if tenant_id:
                        return {"auth": "tenant_key", "role": "operator", "tenant_id": tenant_id}

            raise HTTPException(status_code=403, detail="Unauthorized")

        @self.app.get("/login", response_class=HTMLResponse)
        async def login_page(request: Request):
            """Login page for the web dashboard (cookie-based session)."""
            # If already logged in, go to dashboard.
            if _load_session_from_request(request):
                return RedirectResponse(url="/", status_code=302)
            return HTMLResponse(
                content=(
                    "<!doctype html><html><head><meta charset='utf-8'/>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
                    "<title>NovaPulse Login</title>"
                    "<style>"
                    "body{font-family:system-ui,Arial,sans-serif;background:#0b1020;color:#e6e8ee;"
                    "display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}"
                    ".card{width:100%;max-width:420px;background:#121a33;border:1px solid #1e2a55;"
                    "border-radius:14px;padding:18px 18px 14px;box-shadow:0 14px 40px rgba(0,0,0,.45)}"
                    "h1{margin:0 0 10px;font-size:20px;letter-spacing:.6px}"
                    "label{display:block;margin:10px 0 6px;font-size:12px;opacity:.9}"
                    "input{width:100%;padding:10px 12px;border-radius:10px;border:1px solid #2a3a74;"
                    "background:#0d1328;color:#e6e8ee;outline:none}"
                    "button{width:100%;margin-top:14px;padding:10px 12px;border-radius:10px;"
                    "border:1px solid #3a57b9;background:#1a2c6d;color:#fff;font-weight:700;cursor:pointer}"
                    ".hint{margin-top:10px;font-size:12px;opacity:.8;line-height:1.35}"
                    "</style></head><body>"
                    "<div class='card'>"
                    "<h1>NovaPulse Command Center</h1>"
                    "<form method='post' action='/login'>"
                    f"<label>Username</label><input name='username' autocomplete='username' value='{html.escape(self._admin_username)}'/>"
                    "<label>Password</label><input name='password' type='password' autocomplete='current-password'/>"
                    "<button type='submit'>Login</button>"
                    "</form>"
                    "<div class='hint'>For production/live: set <code>DASHBOARD_ADMIN_PASSWORD_HASH</code> and "
                    "<code>DASHBOARD_SESSION_SECRET</code>. Avoid plaintext passwords in <code>.env</code>.</div>"
                    "</div></body></html>"
                )
            )

        @self.app.post("/login")
        async def login_submit(
            username: str = Form(default=""),
            password: str = Form(default=""),
        ):
            username = (username or "").strip()
            if not secrets.compare_digest(username, self._admin_username):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            if not _verify_admin_password(password):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            resp = RedirectResponse(url="/", status_code=302)
            _issue_session(resp, role="admin", tenant_id=_default_tenant_id())
            return resp

        @self.app.post("/logout")
        async def logout():
            resp = RedirectResponse(url="/login", status_code=302)
            _clear_session(resp)
            return resp

        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard(request: Request):
            """Serve the main dashboard page (requires login when auth is enabled)."""
            if _require_auth_for_reads() and not _load_session_from_request(request):
                return RedirectResponse(url="/login", status_code=302)

            dashboard_path = Path("static/index.html")
            if dashboard_path.exists():
                return HTMLResponse(content=dashboard_path.read_text())
            return HTMLResponse(content="<h1>NovaPulse - Dashboard Loading...</h1>")

        # Mount static files
        static_path = Path("static")
        if static_path.exists():
            self.app.mount("/static", StaticFiles(directory="static"), name="static")

        @self.app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            from fastapi import Response
            return Response(status_code=204)

        # ---- Status Endpoints ----

        @self.app.get("/api/v1/health")
        @self.app.head("/api/v1/health")
        async def health():
            """Probing endpoint for dashboard connectivity."""
            return {"status": "ok"}

        @self.app.get("/api/v1/status")
        @self.app.head("/api/v1/status")
        async def get_status(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get overall system status."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {"status": "initializing"}

            running = any(getattr(e, "_running", False) for e in engines)
            paused = all(getattr(e, "_trading_paused", False) for e in engines)
            scan_count = sum(getattr(e, "_scan_count", 0) for e in engines)
            pairs = []
            for e in engines:
                pairs.extend(getattr(e, "pairs", []) or [])
            pairs = sorted(set(pairs))

            mode = None
            modes = {getattr(e, "mode", None) for e in engines}
            if len(modes) == 1:
                mode = modes.pop()
            else:
                mode = "mixed"

            start_times = [getattr(e, "_start_time", 0.0) for e in engines if getattr(e, "_start_time", 0.0)]
            start_time = min(start_times) if start_times else 0.0

            es_clients = [getattr(e, "es_client", None) for e in engines if getattr(e, "es_client", None)]
            es_queue_depth = sum(int(getattr(es, "queue_depth", 0) or 0) for es in es_clients)
            es_queue_capacity = sum(int(getattr(es, "queue_capacity", 0) or 0) for es in es_clients)
            es_dropped_docs = sum(int(getattr(es, "dropped_docs", 0) or 0) for es in es_clients)
            es_connected = sum(1 for es in es_clients if bool(getattr(es, "connected", False)))

            return {
                "status": "running" if running else "stopped",
                "mode": mode,
                "canary_mode": any(bool(getattr(e, "canary_mode", False)) for e in engines),
                "uptime_seconds": time.time() - start_time if start_time else 0.0,
                "scan_count": scan_count,
                "version": __version__,
                "pairs": pairs,
                "scan_interval": min(
                    (getattr(e, "scan_interval", 0) for e in engines),
                    default=0,
                ),
                "ws_connected": any(
                    (getattr(e, "ws_client", None) and e.ws_client.is_connected)
                    for e in engines
                ),
                "paused": paused,
                "auto_pause_reason": next(
                    (
                        getattr(e, "_auto_pause_reason", "")
                        for e in engines
                        if getattr(e, "_auto_pause_reason", "")
                    ),
                    "",
                ),
                "exchanges": [
                    {
                        "name": getattr(e, "exchange_name", "unknown"),
                        "running": getattr(e, "_running", False),
                        "paused": getattr(e, "_trading_paused", False),
                        "ws_connected": (
                            e.ws_client.is_connected if getattr(e, "ws_client", None) else False
                        ),
                    }
                    for e in engines
                ],
                "es_queue": {
                    "engines_with_es": len(es_clients),
                    "connected": es_connected,
                    "depth": es_queue_depth,
                    "capacity": es_queue_capacity,
                    "dropped_docs": es_dropped_docs,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        @self.app.get("/api/v1/ops/heartbeat")
        async def ops_heartbeat(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """
            Operator heartbeat endpoint for external watchdogs/VPS probes.
            Includes per-engine stale pair counts and connectivity status.
            """
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {"status": "initializing", "engines": []}

            rows = []
            for eng in engines:
                stale_pairs = []
                md = getattr(eng, "market_data", None)
                for pair in getattr(eng, "pairs", []) or []:
                    if md and md.is_stale(pair, max_age_seconds=600):
                        stale_pairs.append(pair)
                rows.append(
                    {
                        "exchange": str(getattr(eng, "exchange_name", "unknown")),
                        "account_id": str(getattr(eng, "tenant_id", "default")),
                        "mode": str(getattr(eng, "mode", "")),
                        "running": bool(getattr(eng, "_running", False)),
                        "paused": bool(getattr(eng, "_trading_paused", False)),
                        "ws_connected": bool(
                            getattr(eng, "ws_client", None)
                            and getattr(eng.ws_client, "is_connected", False)
                        ),
                        "pairs_total": len(getattr(eng, "pairs", []) or []),
                        "stale_pairs": stale_pairs,
                        "stale_pairs_count": len(stale_pairs),
                        "scan_interval_seconds": int(getattr(eng, "scan_interval", 0) or 0),
                    }
                )

            overall_ok = all(r["running"] for r in rows) and all(r["stale_pairs_count"] == 0 for r in rows)
            return {
                "status": "ok" if overall_ok else "degraded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "engines": rows,
            }

        def _default_tenant_id() -> str:
            primary = self._get_primary_engine()
            if primary and getattr(primary, "config", None):
                return primary.config.billing.tenant.default_tenant_id
            return "default"

        async def _resolve_tenant_from_credentials(
            requested_tenant_id: str = "",
            api_key: str = "",
            require_api_key: bool = False,
        ) -> str:
            return await self.resolve_tenant_id(
                requested_tenant_id=requested_tenant_id,
                api_key=api_key,
                require_api_key=require_api_key,
            )

        async def _resolve_tenant_id_read(
            request: Request,
            x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ) -> str:
            """Resolve tenant_id for read endpoints from either session or API key context."""
            requested = (x_tenant_id or "").strip()
            ctx = await _require_read_access(request, x_api_key=x_api_key)

            if ctx.get("auth") == "session":
                if ctx.get("role") == "admin":
                    return requested or _default_tenant_id()
                return ctx.get("tenant_id") or _default_tenant_id()

            if ctx.get("auth") in ("key", "tenant_key"):
                return await _resolve_tenant_from_credentials(
                    requested_tenant_id=requested,
                    api_key=x_api_key,
                    require_api_key=True,
                )

            # No auth required -> never trust arbitrary requested tenant IDs.
            return _default_tenant_id()

        @self.app.get("/api/v1/trades")
        async def get_trades(
            limit: int = Query(default=100, ge=1, le=1000),
            tenant_id: str = Depends(_resolve_tenant_id_read),
        ):
            """Get trade history."""
            engines = self._get_engines()
            if not engines:
                return []

            if self._engines_share_db(engines):
                primary = self._get_primary_engine()
                if not primary or not getattr(primary, "db", None):
                    return []
                return await primary.db.get_trade_history(limit=limit, tenant_id=tenant_id)

            trades: List[Dict[str, Any]] = []
            for eng in engines:
                if not getattr(eng, "db", None):
                    continue
                rows = await eng.db.get_trade_history(limit=limit, tenant_id=tenant_id)
                for row in rows:
                    row["exchange"] = getattr(eng, "exchange_name", "unknown")
                trades.extend(rows)

            trades.sort(key=lambda t: t.get("exit_time") or "", reverse=True)
            return trades[:limit]

        @self.app.get("/api/v1/export/trades.csv")
        async def export_trades_csv(
            limit: int = Query(default=1000, ge=1, le=10000),
            tenant_id: str = Depends(_resolve_tenant_id_read),
        ):
            """Export recent trades as CSV (download)."""
            engines = self._get_engines()
            if not engines:
                raise HTTPException(status_code=503, detail="Bot not running")
            if not self._engines_share_db(engines):
                raise HTTPException(status_code=400, detail="CSV export requires a shared DB")
            primary = self._get_primary_engine()
            if not primary or not getattr(primary, "db", None):
                raise HTTPException(status_code=503, detail="DB not available")

            rows = await primary.db.get_trade_history(limit=limit, tenant_id=tenant_id)

            def _iter_csv():
                buf = io.StringIO()
                w = csv.writer(buf)
                cols = [
                    "id",
                    "pair",
                    "side",
                    "status",
                    "entry_time",
                    "exit_time",
                    "entry_price",
                    "exit_price",
                    "quantity",
                    "size_usd",
                    "pnl",
                    "pnl_pct",
                    "stop_loss",
                    "take_profit",
                    "confidence",
                    "strategy",
                    "reason",
                    "metadata",
                ]
                w.writerow(cols)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

                for r in rows:
                    w.writerow([r.get(c, "") for c in cols])
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)

            headers = {"Content-Disposition": "attachment; filename=trades.csv"}
            return StreamingResponse(_iter_csv(), media_type="text/csv", headers=headers)

        @self.app.get("/api/v1/positions")
        async def get_positions(tenant_id: str = Depends(_resolve_tenant_id_read)):
            """Get open positions."""
            engines = self._get_engines()
            if not engines:
                return []

            positions: List[Dict[str, Any]] = []
            for eng in engines:
                if not getattr(eng, "db", None):
                    continue
                rows = await eng.db.get_open_trades(tenant_id=tenant_id)
                rows = [p for p in rows if abs(p.get("quantity", 0) or 0) > 0.00000001]
                fee_rate = getattr(getattr(eng, "config", None), "exchange", None)
                fee_rate = getattr(fee_rate, "taker_fee", 0.0)
                for pos in rows:
                    current_price = eng.market_data.get_latest_price(pos["pair"])
                    if current_price > 0:
                        notional = pos["entry_price"] * pos["quantity"]
                        if pos["side"] == "buy":
                            gross = (current_price - pos["entry_price"]) * pos["quantity"]
                        else:
                            gross = (pos["entry_price"] - current_price) * pos["quantity"]
                        est_exit_fee = abs(current_price * pos["quantity"]) * fee_rate
                        pos["unrealized_pnl"] = gross - est_exit_fee
                        pos["current_price"] = current_price
                        pos["unrealized_pnl_pct"] = (
                            pos["unrealized_pnl"] / notional
                        ) if notional > 0 else 0
                    pos["exchange"] = getattr(eng, "exchange_name", "unknown")
                positions.extend(rows)

            positions.sort(key=lambda p: p.get("entry_time") or "", reverse=True)
            return positions

        @self.app.get("/api/v1/performance")
        async def get_performance(tenant_id: str = Depends(_resolve_tenant_id_read)):
            """Get performance metrics including unrealized P&L."""
            engines = self._get_engines()
            if not engines:
                return {}

            stats_list: List[Dict[str, Any]] = []
            for eng in engines:
                if getattr(eng, "db", None):
                    stats_list.append(await eng.db.get_performance_stats(tenant_id=tenant_id))

            stats = self._aggregate_performance_stats(stats_list)
            risk_report = self._aggregate_risk_reports(
                [eng.risk_manager.get_risk_report() for eng in engines if getattr(eng, "risk_manager", None)]
            )

            # Add unrealized P&L from open positions
            unrealized = 0.0
            for eng in engines:
                if not getattr(eng, "db", None):
                    continue
                positions = await eng.db.get_open_trades(tenant_id=tenant_id)
                fee_rate = getattr(getattr(eng, "config", None), "exchange", None)
                fee_rate = getattr(fee_rate, "taker_fee", 0.0)
                for pos in positions:
                    cp = eng.market_data.get_latest_price(pos["pair"])
                    if cp > 0:
                        if pos["side"] == "buy":
                            gross = (cp - pos["entry_price"]) * pos["quantity"]
                        else:
                            gross = (pos["entry_price"] - cp) * pos["quantity"]
                        est_entry_fee = abs(pos["entry_price"] * pos["quantity"]) * fee_rate
                        est_exit_fee = abs(cp * pos["quantity"]) * fee_rate
                        unrealized += (gross - est_entry_fee - est_exit_fee)

            stats["unrealized_pnl"] = round(unrealized, 2)
            stats["total_equity"] = round(
                (risk_report.get("bankroll", 0.0) or 0.0) + unrealized, 2
            )
            return {**stats, **risk_report}

        @self.app.get("/api/v1/strategies")
        async def get_strategies(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get strategy performance stats."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return []
            if len(engines) == 1:
                return engines[0].get_algorithm_stats()
            combined: List[Dict[str, Any]] = []
            for eng in engines:
                stats = eng.get_algorithm_stats()
                for s in stats:
                    s = dict(s)
                    s["exchange"] = getattr(eng, "exchange_name", "unknown")
                    combined.append(s)
            return combined

        @self.app.get("/api/v1/strategy-performance")
        async def get_strategy_performance(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
            tenant_id: str = Depends(_resolve_tenant_id_read),
        ):
            """Get per-strategy win rate and PnL stats from trade history."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {}
            for eng in engines:
                if getattr(eng, "db", None):
                    return await eng.db.get_strategy_stats(tenant_id=tenant_id)
            return {}

        @self.app.get("/api/v1/risk")
        async def get_risk(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get risk management report."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {}
            if len(engines) == 1:
                return engines[0].risk_manager.get_risk_report()
            reports = [eng.risk_manager.get_risk_report() for eng in engines if getattr(eng, "risk_manager", None)]
            return self._aggregate_risk_reports(reports)

        @self.app.get("/api/v1/thoughts")
        async def get_thoughts(
            limit: int = 50,
            tenant_id: str = Depends(_resolve_tenant_id_read),
        ):
            """Get AI thought feed."""
            engines = self._get_engines()
            if not engines:
                return []

            if self._engines_share_db(engines):
                primary = self._get_primary_engine()
                if not primary or not getattr(primary, "db", None):
                    return []
                return await primary.db.get_thoughts(limit=limit, tenant_id=tenant_id)

            thoughts: List[Dict[str, Any]] = []
            for eng in engines:
                if not getattr(eng, "db", None):
                    continue
                rows = await eng.db.get_thoughts(limit=limit, tenant_id=tenant_id)
                for row in rows:
                    row["exchange"] = getattr(eng, "exchange_name", "unknown")
                thoughts.extend(rows)
            thoughts.sort(key=lambda t: t.get("timestamp") or "", reverse=True)
            return thoughts[:limit]

        @self.app.get("/api/v1/scanner")
        async def get_scanner(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get market scanner status."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {}
            scanner_data: Dict[str, Any] = {}
            for eng in engines:
                exchange = str(getattr(eng, "exchange_name", "unknown")).lower()
                asset_class = "stock" if exchange == "stocks" else "crypto"
                account = str(getattr(eng, "tenant_id", "default"))
                for pair in getattr(eng, "pairs", []) or []:
                    label = f"{pair} ({exchange}:{account})" if len(engines) > 1 else pair
                    scanner_data[label] = {
                        "pair": pair,
                        "exchange": exchange,
                        "account_id": account,
                        "asset_class": asset_class,
                        "price": eng.market_data.get_latest_price(pair) if getattr(eng, "market_data", None) else 0.0,
                        "bars": eng.market_data.get_bar_count(pair) if getattr(eng, "market_data", None) else 0,
                        "stale": eng.market_data.is_stale(pair) if getattr(eng, "market_data", None) else True,
                    }
            return scanner_data

        @self.app.get("/api/v1/chart")
        async def get_chart_data(
            request: Request,
            pair: str = Query(..., min_length=1),
            timeframe: str = Query(default="5m"),
            exchange: str = Query(default=""),
            account_id: str = Query(default=""),
            limit: int = Query(default=320, ge=60, le=1500),
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get OHLCV candles for the dashboard chart viewer."""
            await _require_read_access(request, x_api_key=x_api_key)

            p = (pair or "").strip().upper()
            ex, acct = self._split_exchange_account(exchange, account_id)
            tf = self._normalize_chart_timeframe(timeframe)

            eng = self._resolve_chart_engine(p, ex, acct)
            if not eng:
                return {
                    "pair": p,
                    "exchange": ex or "unknown",
                    "account_id": acct or "default",
                    "timeframe": tf,
                    "candles": [],
                }

            ex_name = str(getattr(eng, "exchange_name", "unknown")).lower()
            eng_account = str(getattr(eng, "tenant_id", "default"))
            source = "cache"
            if ex_name == "stocks":
                candles = await self._get_stock_chart_bars(
                    eng,
                    symbol=p,
                    timeframe=tf,
                    limit=limit,
                )
                source = "polygon"
            else:
                candles, source = await self._get_crypto_chart_bars(
                    eng,
                    pair=p,
                    timeframe=tf,
                    limit=limit,
                )

            return {
                "pair": p,
                "exchange": ex_name,
                "account_id": eng_account,
                "timeframe": tf,
                "source": source,
                "candles": candles,
            }

        @self.app.get("/api/v1/execution")
        async def get_execution(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get execution statistics."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {}
            if len(engines) == 1:
                return engines[0].executor.get_execution_stats()
            agg: Dict[str, Any] = {}
            for eng in engines:
                stats = eng.executor.get_execution_stats()
                for k, v in stats.items():
                    if isinstance(v, (int, float)):
                        agg[k] = agg.get(k, 0) + v
                    else:
                        agg[k] = v
            return agg

        @self.app.get("/api/v1/integrations/exchanges")
        async def get_exchange_integrations(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """List exchange integration status and connectivity health."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            rows: List[Dict[str, Any]] = []
            for eng in engines:
                ws = getattr(eng, "ws_client", None)
                rest = getattr(eng, "rest_client", None)
                rows.append(
                    {
                        "exchange": str(getattr(eng, "exchange_name", "unknown")).lower(),
                        "mode": str(getattr(eng, "mode", "")),
                        "tenant_id": str(getattr(eng, "tenant_id", "")),
                        "pairs": list(getattr(eng, "pairs", []) or []),
                        "ws_connected": bool(getattr(ws, "is_connected", False)) if ws else False,
                        "rest_client_ready": bool(rest is not None),
                        "market_data_ready": bool(getattr(eng, "market_data", None) is not None),
                        "executor_ready": bool(getattr(eng, "executor", None) is not None),
                    }
                )
            return {"integrations": rows, "count": len(rows)}

        @self.app.get("/api/v1/storage")
        async def get_storage_contract(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Return canonical persistence contract and resolved storage targets."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            rows: List[Dict[str, Any]] = []
            for eng in engines:
                db = getattr(eng, "db", None)
                db_rel = str(getattr(db, "db_path", "") or "")
                db_abs = str(Path(db_rel).resolve()) if db_rel else ""
                rows.append(
                    {
                        "exchange": str(getattr(eng, "exchange_name", "unknown")).lower(),
                        "account_id": str(getattr(eng, "tenant_id", "default")),
                        "db_path": db_rel,
                        "db_path_abs": db_abs,
                        "db_exists": bool(db_abs and Path(db_abs).exists()),
                        "db_wal_exists": bool(db_abs and Path(f"{db_abs}-wal").exists()),
                        "db_shm_exists": bool(db_abs and Path(f"{db_abs}-shm").exists()),
                    }
                )

            primary = engines[0] if engines else None
            es_cfg = getattr(getattr(primary, "config", None), "elasticsearch", None)
            return {
                "canonical_ledger": "sqlite",
                "elasticsearch_role": "analytics_mirror",
                "es_enabled": bool(getattr(es_cfg, "enabled", False)),
                "es_index_prefix": str(getattr(es_cfg, "index_prefix", "novapulse")),
                "es_target": (
                    "cloud"
                    if bool(getattr(es_cfg, "cloud_id", ""))
                    else ("hosts" if bool(getattr(es_cfg, "hosts", [])) else "disabled")
                ),
                "engines": rows,
            }

        _MARKETPLACE_TEMPLATES: Dict[str, Dict[str, Any]] = {
            "keltner_focus": {
                "id": "keltner_focus",
                "name": "Keltner Focus",
                "description": "Bias toward Keltner + mean reversion for disciplined entries.",
                "strategies": {
                    "keltner": {"enabled": True, "weight": 0.42},
                    "mean_reversion": {"enabled": True, "weight": 0.25},
                    "trend": {"enabled": True, "weight": 0.10},
                    "ichimoku": {"enabled": True, "weight": 0.08},
                    "order_flow": {"enabled": True, "weight": 0.08},
                    "stochastic_divergence": {"enabled": True, "weight": 0.07},
                    "volatility_squeeze": {"enabled": False, "weight": 0.0},
                    "supertrend": {"enabled": False, "weight": 0.0},
                    "reversal": {"enabled": False, "weight": 0.0},
                },
                "ai": {"confluence_threshold": 2, "min_confidence": 0.58, "min_risk_reward_ratio": 1.2},
            },
            "trend_breakout": {
                "id": "trend_breakout",
                "name": "Trend + Breakout",
                "description": "Trend-following profile for momentum markets.",
                "strategies": {
                    "trend": {"enabled": True, "weight": 0.28},
                    "ichimoku": {"enabled": True, "weight": 0.22},
                    "supertrend": {"enabled": True, "weight": 0.20},
                    "volatility_squeeze": {"enabled": True, "weight": 0.16},
                    "order_flow": {"enabled": True, "weight": 0.14},
                    "keltner": {"enabled": False, "weight": 0.0},
                    "mean_reversion": {"enabled": False, "weight": 0.0},
                    "stochastic_divergence": {"enabled": False, "weight": 0.0},
                    "reversal": {"enabled": False, "weight": 0.0},
                },
                "ai": {"confluence_threshold": 3, "min_confidence": 0.62, "min_risk_reward_ratio": 1.4},
            },
            "balanced_all_weather": {
                "id": "balanced_all_weather",
                "name": "Balanced All-Weather",
                "description": "Balanced profile across trend, mean-revert, and volatility regimes.",
                "strategies": {
                    "keltner": {"enabled": True, "weight": 0.18},
                    "mean_reversion": {"enabled": True, "weight": 0.16},
                    "trend": {"enabled": True, "weight": 0.14},
                    "ichimoku": {"enabled": True, "weight": 0.12},
                    "order_flow": {"enabled": True, "weight": 0.12},
                    "stochastic_divergence": {"enabled": True, "weight": 0.10},
                    "volatility_squeeze": {"enabled": True, "weight": 0.08},
                    "supertrend": {"enabled": True, "weight": 0.06},
                    "reversal": {"enabled": True, "weight": 0.04},
                },
                "ai": {"confluence_threshold": 2, "min_confidence": 0.60, "min_risk_reward_ratio": 1.25},
            },
        }

        @self.app.get("/api/v1/marketplace/strategies")
        async def list_marketplace_strategies(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """List built-in strategy templates (marketplace-style packs)."""
            await _require_read_access(request, x_api_key=x_api_key)
            return {"templates": list(_MARKETPLACE_TEMPLATES.values())}

        @self.app.post("/api/v1/marketplace/strategies/apply")
        async def apply_marketplace_strategy(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Apply a strategy template to one or more running engines."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)

            template_id = str(body.get("template_id", "")).strip()
            if not template_id or template_id not in _MARKETPLACE_TEMPLATES:
                raise HTTPException(status_code=400, detail="Unknown template_id")
            template = _MARKETPLACE_TEMPLATES[template_id]

            target_exchange = str(body.get("exchange", "")).strip().lower()
            target_tenant = str(body.get("tenant_id", "")).strip()
            apply_all = bool(body.get("apply_all", False))
            persist = bool(body.get("persist", True))

            engines = self._get_engines()
            if not engines:
                raise HTTPException(status_code=503, detail="Bot not running")

            targeted = []
            for eng in engines:
                if target_exchange and str(getattr(eng, "exchange_name", "")).lower() != target_exchange:
                    continue
                if target_tenant and str(getattr(eng, "tenant_id", "")) != target_tenant:
                    continue
                targeted.append(eng)
                if not apply_all:
                    break

            if not targeted:
                raise HTTPException(status_code=404, detail="No matching engine for requested filters")

            strategy_updates = template.get("strategies", {})
            ai_updates = template.get("ai", {})
            yaml_updates: Dict[str, Dict[str, Any]] = {
                "strategies": strategy_updates,
                "ai": ai_updates,
            }

            applied = []
            for eng in targeted:
                cfg = eng.config
                for strat_name, vals in strategy_updates.items():
                    strat_cfg = getattr(cfg.strategies, strat_name, None)
                    if not strat_cfg:
                        continue
                    if "enabled" in vals:
                        strat_cfg.enabled = bool(vals["enabled"])
                    if "weight" in vals:
                        strat_cfg.weight = float(vals["weight"])
                if "confluence_threshold" in ai_updates:
                    cfg.ai.confluence_threshold = int(ai_updates["confluence_threshold"])
                if "min_confidence" in ai_updates:
                    cfg.ai.min_confidence = float(ai_updates["min_confidence"])
                if "min_risk_reward_ratio" in ai_updates:
                    cfg.ai.min_risk_reward_ratio = float(ai_updates["min_risk_reward_ratio"])

                if getattr(eng, "confluence", None):
                    eng.confluence.configure_strategies(
                        cfg.strategies.model_dump(),
                        single_strategy_mode=getattr(cfg.trading, "single_strategy_mode", None),
                    )
                    eng.confluence.confluence_threshold = cfg.ai.confluence_threshold
                    eng.confluence.min_confidence = cfg.ai.min_confidence

                if getattr(eng, "db", None):
                    await eng.db.log_thought(
                        "strategy",
                        f"Marketplace template applied: {template_id}",
                        severity="info",
                        metadata={
                            "template_id": template_id,
                            "template_name": template.get("name"),
                        },
                        tenant_id=getattr(eng, "tenant_id", "default"),
                    )
                applied.append(
                    {
                        "exchange": str(getattr(eng, "exchange_name", "unknown")),
                        "tenant_id": str(getattr(eng, "tenant_id", "default")),
                    }
                )

            if persist:
                try:
                    from src.core.config import save_to_yaml

                    save_to_yaml(yaml_updates)
                except Exception as e:
                    logger.warning("Marketplace template persistence failed", error=repr(e))

            return {
                "ok": True,
                "template_id": template_id,
                "applied_to": applied,
            }

        @self.app.get("/api/v1/copy-trading/providers")
        async def list_copy_trading_providers(
            request: Request,
            tenant_id: str = Depends(_resolve_tenant_id_read),
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """List copy-trading signal providers for the tenant."""
            await _require_read_access(request, x_api_key=x_api_key)
            primary = self._get_primary_engine()
            if not primary or not getattr(primary, "db", None):
                return {"providers": []}
            rows = await primary.db.get_copy_trading_providers(tenant_id=tenant_id)
            for row in rows:
                if row.get("webhook_secret"):
                    row["webhook_secret"] = "***"
            return {"providers": rows}

        @self.app.post("/api/v1/copy-trading/providers")
        async def create_copy_trading_provider(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Create or replace a copy-trading provider definition."""
            ctx = await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            primary = self._get_primary_engine()
            if not primary or not getattr(primary, "db", None):
                raise HTTPException(status_code=503, detail="Bot DB unavailable")

            provider_id = str(body.get("provider_id") or f"provider_{uuid.uuid4().hex[:10]}").strip().lower()
            name = str(body.get("name") or provider_id).strip()
            source = str(body.get("source") or "").strip().lower()
            enabled = bool(body.get("enabled", True))
            webhook_secret = str(body.get("webhook_secret") or "").strip()
            metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
            tenant_id = ctx.get("tenant_id") if ctx.get("role") != "admin" else str(body.get("tenant_id") or ctx.get("tenant_id") or "default")

            await primary.db.upsert_copy_trading_provider(
                provider_id=provider_id,
                name=name,
                tenant_id=tenant_id,
                source=source,
                enabled=enabled,
                webhook_secret=webhook_secret,
                metadata=metadata,
            )
            return {"ok": True, "provider_id": provider_id}

        @self.app.patch("/api/v1/copy-trading/providers/{provider_id}")
        async def update_copy_trading_provider(
            request: Request,
            provider_id: str,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Update an existing copy-trading provider definition."""
            ctx = await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            primary = self._get_primary_engine()
            if not primary or not getattr(primary, "db", None):
                raise HTTPException(status_code=503, detail="Bot DB unavailable")

            tenant_id = ctx.get("tenant_id") if ctx.get("role") != "admin" else str(body.get("tenant_id") or ctx.get("tenant_id") or "default")
            current = await primary.db.get_copy_trading_provider(provider_id=provider_id, tenant_id=tenant_id)
            if not current:
                raise HTTPException(status_code=404, detail="Provider not found")

            await primary.db.upsert_copy_trading_provider(
                provider_id=provider_id,
                name=str(body.get("name", current.get("name") or provider_id)).strip(),
                tenant_id=tenant_id,
                source=str(body.get("source", current.get("source") or "")).strip().lower(),
                enabled=bool(body.get("enabled", current.get("enabled", True))),
                webhook_secret=str(body.get("webhook_secret", current.get("webhook_secret", ""))).strip(),
                metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else current.get("metadata", {}),
            )
            return {"ok": True, "provider_id": provider_id}

        @self.app.get("/api/v1/backtest/runs")
        async def list_backtest_runs(
            request: Request,
            limit: int = Query(default=25, ge=1, le=200),
            tenant_id: str = Depends(_resolve_tenant_id_read),
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """List historical backtest/optimization runs."""
            await _require_read_access(request, x_api_key=x_api_key)
            engines = self._get_engines()
            if not engines:
                return {"runs": []}

            runs: List[Dict[str, Any]] = []
            if self._engines_share_db(engines):
                primary = self._get_primary_engine()
                if primary and getattr(primary, "db", None):
                    runs = await primary.db.get_backtest_runs(limit=limit, tenant_id=tenant_id)
                    for run in runs:
                        run.setdefault("exchange", getattr(primary, "exchange_name", "unknown"))
            else:
                for eng in engines:
                    if not getattr(eng, "db", None):
                        continue
                    rows = await eng.db.get_backtest_runs(limit=limit, tenant_id=tenant_id)
                    for row in rows:
                        row["exchange"] = row.get("exchange") or getattr(eng, "exchange_name", "unknown")
                    runs.extend(rows)
                runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                runs = runs[:limit]
            return {"runs": runs}

        @self.app.post("/api/v1/backtest/run")
        async def run_backtest(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Run a backtest using recent historical candles and persist the result."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)

            pair = str(body.get("pair", "")).strip().upper()
            if not pair:
                raise HTTPException(status_code=400, detail="pair is required")

            tf = self._normalize_chart_timeframe(str(body.get("timeframe", "5m")))
            exchange = str(body.get("exchange", "")).strip().lower()
            account_id = str(body.get("account_id", "")).strip().lower()
            bars = max(120, min(int(body.get("bars", 500) or 500), 5000))
            mode = str(body.get("mode", "parity")).strip().lower()
            if mode not in ("parity", "simple"):
                raise HTTPException(status_code=400, detail="mode must be parity or simple")

            eng = self._resolve_chart_engine(pair, exchange, account_id)
            if not eng:
                raise HTTPException(status_code=404, detail="No engine found for pair/exchange/account")

            if str(getattr(eng, "exchange_name", "")).lower() == "stocks":
                candles = await self._get_stock_chart_bars(
                    eng,
                    symbol=pair,
                    timeframe=tf,
                    limit=bars,
                )
                source = "polygon"
            else:
                candles, source = await self._get_crypto_chart_bars(
                    eng,
                    pair=pair,
                    timeframe=tf,
                    limit=bars,
                )

            if len(candles) < 120:
                raise HTTPException(status_code=400, detail=f"insufficient candle history: {len(candles)}")

            try:
                initial_balance = float(body.get("initial_balance", eng.config.risk.initial_bankroll))
            except Exception:
                initial_balance = float(eng.config.risk.initial_bankroll)
            try:
                risk_per_trade = float(body.get("risk_per_trade", eng.config.risk.max_risk_per_trade))
            except Exception:
                risk_per_trade = float(eng.config.risk.max_risk_per_trade)
            try:
                max_position_pct = float(body.get("max_position_pct", 0.05))
            except Exception:
                max_position_pct = 0.05

            from src.ml.backtester import Backtester

            slippage_pct, fee_pct = self._resolve_backtest_friction(eng, body)
            backtester = Backtester(
                initial_balance=initial_balance,
                risk_per_trade=risk_per_trade,
                max_position_pct=max_position_pct,
                slippage_pct=slippage_pct,
                fee_pct=fee_pct,
            )
            df = self._candles_to_dataframe(candles)
            started_at = datetime.now(timezone.utc).isoformat()

            if mode == "parity":
                result = await backtester.run(
                    pair=pair,
                    ohlcv_data=df,
                    mode="parity",
                    config=eng.config,
                    predictor=getattr(eng, "predictor", None),
                )
            else:
                confluence_threshold = int(body.get("confluence_threshold", eng.config.ai.confluence_threshold) or eng.config.ai.confluence_threshold)
                result = await backtester.run(
                    pair=pair,
                    ohlcv_data=df,
                    mode="simple",
                    confluence_threshold=max(1, confluence_threshold),
                )

            run_id = f"bt_{uuid.uuid4().hex[:12]}"
            completed_at = datetime.now(timezone.utc).isoformat()
            result_dict = result.to_dict()
            payload = {
                "run_id": run_id,
                "run_type": "backtest",
                "pair": pair,
                "exchange": str(getattr(eng, "exchange_name", "unknown")),
                "account_id": str(getattr(eng, "tenant_id", "default")),
                "timeframe": tf,
                "bars": len(candles),
                "mode": mode,
                "source": source,
                "result": result_dict,
            }

            if getattr(eng, "db", None):
                await eng.db.insert_backtest_run(
                    run_id=run_id,
                    pair=pair,
                    run_type="backtest",
                    status="completed",
                    mode=mode,
                    exchange=str(getattr(eng, "exchange_name", "unknown")),
                    timeframe=tf,
                    params={
                        "bars": len(candles),
                        "source": source,
                        "initial_balance": initial_balance,
                        "risk_per_trade": risk_per_trade,
                        "max_position_pct": max_position_pct,
                        "slippage_pct": slippage_pct,
                        "fee_pct": fee_pct,
                    },
                    result=result_dict,
                    tenant_id=getattr(eng, "tenant_id", "default"),
                    started_at=started_at,
                    completed_at=completed_at,
                )

            return payload

        @self.app.post("/api/v1/backtest/optimize")
        async def optimize_backtest(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """
            Run a compact parameter optimization sweep for confluence/confidence thresholds.
            """
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)

            pair = str(body.get("pair", "")).strip().upper()
            if not pair:
                raise HTTPException(status_code=400, detail="pair is required")
            tf = self._normalize_chart_timeframe(str(body.get("timeframe", "5m")))
            exchange = str(body.get("exchange", "")).strip().lower()
            account_id = str(body.get("account_id", "")).strip().lower()
            bars = max(120, min(int(body.get("bars", 500) or 500), 5000))
            max_runs = max(1, min(int(body.get("max_runs", 12) or 12), 36))

            eng = self._resolve_chart_engine(pair, exchange, account_id)
            if not eng:
                raise HTTPException(status_code=404, detail="No engine found for pair/exchange/account")

            if str(getattr(eng, "exchange_name", "")).lower() == "stocks":
                candles = await self._get_stock_chart_bars(
                    eng,
                    symbol=pair,
                    timeframe=tf,
                    limit=bars,
                )
                source = "polygon"
            else:
                candles, source = await self._get_crypto_chart_bars(
                    eng,
                    pair=pair,
                    timeframe=tf,
                    limit=bars,
                )
            if len(candles) < 120:
                raise HTTPException(status_code=400, detail=f"insufficient candle history: {len(candles)}")

            from src.core.config import load_config_with_overrides
            from src.ml.backtester import Backtester

            conf_values = body.get("min_confidence_values", [0.55, 0.60, 0.65])
            confl_values = body.get("confluence_threshold_values", [2, 3, 4])
            rr_values = body.get(
                "min_risk_reward_values",
                [max(1.0, float(getattr(eng.config.ai, "min_risk_reward_ratio", 1.2)))],
            )
            if not isinstance(conf_values, list) or not isinstance(confl_values, list) or not isinstance(rr_values, list):
                raise HTTPException(status_code=400, detail="parameter value fields must be lists")

            grid: List[Dict[str, Any]] = []
            for c in conf_values:
                for k in confl_values:
                    for rr in rr_values:
                        try:
                            grid.append(
                                {
                                    "min_confidence": max(0.3, min(0.95, float(c))),
                                    "confluence_threshold": max(1, min(8, int(k))),
                                    "min_risk_reward_ratio": max(0.5, min(5.0, float(rr))),
                                }
                            )
                        except Exception:
                            continue
            grid = grid[:max_runs]
            if not grid:
                raise HTTPException(status_code=400, detail="empty parameter grid")

            df = self._candles_to_dataframe(candles)
            slippage_pct, fee_pct = self._resolve_backtest_friction(eng, body)
            backtester = Backtester(
                initial_balance=float(eng.config.risk.initial_bankroll),
                risk_per_trade=float(eng.config.risk.max_risk_per_trade),
                max_position_pct=0.05,
                slippage_pct=slippage_pct,
                fee_pct=fee_pct,
            )

            started_at = datetime.now(timezone.utc).isoformat()
            leaderboard: List[Dict[str, Any]] = []
            for params in grid:
                overrides = {
                    "ai": {
                        "min_confidence": params["min_confidence"],
                        "confluence_threshold": params["confluence_threshold"],
                        "min_risk_reward_ratio": params["min_risk_reward_ratio"],
                    }
                }
                cfg_variant = load_config_with_overrides(overrides=overrides)
                cfg_variant.exchange = eng.config.exchange
                cfg_variant.trading = eng.config.trading
                cfg_variant.strategies = eng.config.strategies
                cfg_variant.risk = eng.config.risk
                cfg_variant.ml = eng.config.ml

                result = await backtester.run(
                    pair=pair,
                    ohlcv_data=df,
                    mode="parity",
                    config=cfg_variant,
                    predictor=getattr(eng, "predictor", None),
                )
                metrics = result.to_dict()
                score = (
                    float(metrics.get("total_return_pct", 0.0))
                    + (float(metrics.get("win_rate", 0.0)) * 30.0)
                    - (float(metrics.get("max_drawdown", 0.0)) * 80.0)
                )
                leaderboard.append(
                    {
                        "params": params,
                        "score": round(score, 4),
                        "metrics": metrics,
                    }
                )

            leaderboard.sort(key=lambda r: r.get("score", 0.0), reverse=True)
            best = leaderboard[0] if leaderboard else {}
            run_id = f"opt_{uuid.uuid4().hex[:12]}"
            completed_at = datetime.now(timezone.utc).isoformat()

            if getattr(eng, "db", None):
                await eng.db.insert_backtest_run(
                    run_id=run_id,
                    pair=pair,
                    run_type="optimization",
                    status="completed",
                    mode="parity",
                    exchange=str(getattr(eng, "exchange_name", "unknown")),
                    timeframe=tf,
                    params={
                        "bars": len(candles),
                        "source": source,
                        "grid_size": len(grid),
                        "slippage_pct": slippage_pct,
                        "fee_pct": fee_pct,
                    },
                    result={
                        "best": best,
                        "top": leaderboard[:10],
                    },
                    tenant_id=getattr(eng, "tenant_id", "default"),
                    started_at=started_at,
                    completed_at=completed_at,
                )

            return {
                "run_id": run_id,
                "pair": pair,
                "exchange": str(getattr(eng, "exchange_name", "unknown")),
                "account_id": str(getattr(eng, "tenant_id", "default")),
                "timeframe": tf,
                "tested": len(leaderboard),
                "best": best,
                "top": leaderboard[:10],
            }

        @self.app.post("/api/v1/paper/reset")
        async def reset_paper_session(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Reset paper-trading runtime state for a clean simulation cycle."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            engines = self._get_engines()
            if not engines:
                raise HTTPException(status_code=503, detail="Bot not running")

            total_closed = 0
            reset_ts = datetime.now(timezone.utc).isoformat()
            for eng in engines:
                if str(getattr(eng, "mode", "")).lower() != "paper":
                    raise HTTPException(status_code=400, detail="paper reset is only allowed in paper mode")
                executor = getattr(eng, "executor", None)
                if executor:
                    total_closed += await executor.close_all_positions("paper_reset", tenant_id=getattr(eng, "tenant_id", "default"))
                rm = getattr(eng, "risk_manager", None)
                if rm and hasattr(rm, "reset_runtime"):
                    rm.reset_runtime(initial_bankroll=float(getattr(eng.config.risk, "initial_bankroll", rm.initial_bankroll)))
                if getattr(eng, "db", None):
                    await eng.db.set_state("stats_reset_ts", reset_ts)
                    await eng.db.log_thought(
                        "system",
                        "Paper session reset via API",
                        severity="warning",
                        tenant_id=getattr(eng, "tenant_id", "default"),
                    )
            return {"ok": True, "closed_positions": total_closed, "reset_ts": reset_ts}

        @self.app.post("/api/v1/signals/webhook")
        async def signal_webhook(
            request: Request,
            x_signal_signature: str = Header(default="", alias="X-Signal-Signature"),
            x_signal_timestamp: str = Header(default="", alias="X-Signal-Timestamp"),
            x_signal_source: str = Header(default="", alias="X-Signal-Source"),
        ):
            """
            Signed signal intake endpoint for TradingView/custom providers.

            Auth:
            - HMAC SHA256 signature over raw payload bytes.
            - If timestamp is provided, signature must be over `timestamp.payload`.
            """
            primary = self._get_primary_engine()
            cfg = getattr(getattr(primary, "config", None), "webhooks", None) if primary else None
            if not cfg or not getattr(cfg, "enabled", False):
                raise HTTPException(status_code=503, detail="Signal webhooks are disabled")

            raw = await request.body()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON payload")

            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Signal payload must be a JSON object")

            source = (x_signal_source or payload.get("source") or "webhook").strip().lower()
            pair = str(payload.get("pair", "")).strip().upper()
            exchange = str(payload.get("exchange", "")).strip().lower()
            account_id = str(payload.get("account_id", "")).strip().lower()
            eng = self._resolve_chart_engine(pair, exchange, account_id) if pair else None
            if not eng:
                eng = primary
            if not eng:
                raise HTTPException(status_code=503, detail="No engine available")
            if not hasattr(eng, "execute_external_signal"):
                raise HTTPException(status_code=400, detail="Engine does not support external signals")

            provider_id = str(payload.get("provider_id") or "").strip().lower()
            provider = None
            if provider_id and getattr(eng, "db", None):
                provider = await eng.db.get_copy_trading_provider(
                    provider_id=provider_id,
                    tenant_id=getattr(eng, "tenant_id", "default"),
                )
                if not provider or not provider.get("enabled", False):
                    raise HTTPException(status_code=403, detail="Provider disabled or not found")
                provider_source = str(provider.get("source") or "").strip().lower()
                if provider_source and source and provider_source != source:
                    raise HTTPException(status_code=403, detail="Source/provider mismatch")

            secret = (
                str((provider or {}).get("webhook_secret") or "").strip()
                or str(getattr(cfg, "secret", "")).strip()
            )
            if not self._verify_signal_signature(
                raw,
                x_signal_signature,
                secret=secret,
                timestamp=x_signal_timestamp,
                max_skew_seconds=int(getattr(cfg, "max_timestamp_skew_seconds", 300) or 300),
            ):
                raise HTTPException(status_code=401, detail="Invalid signal signature")

            allowed_sources = [str(s).strip().lower() for s in (getattr(cfg, "allowed_sources", []) or []) if str(s).strip()]
            if allowed_sources and source not in allowed_sources:
                raise HTTPException(status_code=403, detail="Signal source not allowed")

            payload_hash = hashlib.sha256(raw).hexdigest()
            event_id = str(payload.get("event_id") or payload.get("id") or "").strip() or f"sig:{payload_hash}"
            if getattr(eng, "db", None):
                if await eng.db.has_processed_signal_webhook_event(event_id):
                    return {"ok": True, "duplicate": True, "event_id": event_id}

            result = await eng.execute_external_signal(payload, source=source)
            if not result.get("ok"):
                raise HTTPException(status_code=400, detail=result.get("error", "Signal rejected"))

            if getattr(eng, "db", None):
                await eng.db.mark_signal_webhook_event_processed(
                    event_id,
                    source=source,
                    payload_hash=payload_hash,
                    tenant_id=getattr(eng, "tenant_id", "default"),
                )

            return {"ok": True, "duplicate": False, "event_id": event_id, "result": result}

        # ---- Settings (all tunable parameters) ----
        def _read_all_settings(engine) -> dict:
            """Read all tunable settings from engine runtime state."""
            cfg = engine.config
            return {
                "ai": {
                    "confluence_threshold": cfg.ai.confluence_threshold,
                    "min_confidence": cfg.ai.min_confidence,
                    "min_risk_reward_ratio": cfg.ai.min_risk_reward_ratio,
                    "obi_counts_as_confluence": cfg.ai.obi_counts_as_confluence,
                    "obi_weight": cfg.ai.obi_weight,
                    "allow_keltner_solo": cfg.ai.allow_keltner_solo,
                    "allow_any_solo": cfg.ai.allow_any_solo,
                    "keltner_solo_min_confidence": cfg.ai.keltner_solo_min_confidence,
                    "solo_min_confidence": cfg.ai.solo_min_confidence,
                },
                "risk": {
                    "max_risk_per_trade": cfg.risk.max_risk_per_trade,
                    "max_daily_loss": cfg.risk.max_daily_loss,
                    "max_daily_trades": cfg.risk.max_daily_trades,
                    "max_position_usd": cfg.risk.max_position_usd,
                    "max_total_exposure_pct": cfg.risk.max_total_exposure_pct,
                    "atr_multiplier_sl": cfg.risk.atr_multiplier_sl,
                    "atr_multiplier_tp": cfg.risk.atr_multiplier_tp,
                    "trailing_activation_pct": cfg.risk.trailing_activation_pct,
                    "trailing_step_pct": cfg.risk.trailing_step_pct,
                    "breakeven_activation_pct": cfg.risk.breakeven_activation_pct,
                    "kelly_fraction": cfg.risk.kelly_fraction,
                    "global_cooldown_seconds_on_loss": cfg.risk.global_cooldown_seconds_on_loss,
                },
                "trading": {
                    "scan_interval_seconds": cfg.trading.scan_interval_seconds,
                    "max_concurrent_positions": cfg.trading.max_concurrent_positions,
                    "cooldown_seconds": cfg.trading.cooldown_seconds,
                    "max_spread_pct": cfg.trading.max_spread_pct,
                    "quiet_hours_utc": cfg.trading.quiet_hours_utc,
                    "max_trades_per_hour": cfg.trading.max_trades_per_hour,
                },
                "monitoring": {
                    "auto_pause_on_stale_data": cfg.monitoring.auto_pause_on_stale_data,
                    "stale_data_pause_after_checks": cfg.monitoring.stale_data_pause_after_checks,
                    "auto_pause_on_ws_disconnect": cfg.monitoring.auto_pause_on_ws_disconnect,
                    "ws_disconnect_pause_after_seconds": cfg.monitoring.ws_disconnect_pause_after_seconds,
                    "auto_pause_on_consecutive_losses": cfg.monitoring.auto_pause_on_consecutive_losses,
                    "consecutive_losses_pause_threshold": cfg.monitoring.consecutive_losses_pause_threshold,
                    "auto_pause_on_drawdown": cfg.monitoring.auto_pause_on_drawdown,
                    "drawdown_pause_pct": cfg.monitoring.drawdown_pause_pct,
                    "emergency_close_on_auto_pause": cfg.monitoring.emergency_close_on_auto_pause,
                },
                "ml": {
                    "retrain_interval_hours": cfg.ml.retrain_interval_hours,
                    "min_samples": cfg.ml.min_samples,
                },
            }

        def _coerce_bool_setting(value: Any, dotpath: str) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                if value in (0, 1):
                    return bool(value)
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid boolean value for {dotpath}",
                )
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("1", "true", "yes", "y", "on"):
                    return True
                if lowered in ("0", "false", "no", "n", "off"):
                    return False
            raise HTTPException(
                status_code=400,
                detail=f"Invalid boolean value for {dotpath}",
            )

        def _apply_live_subsystem_updates(engine: Any, changed_paths: Set[str]) -> None:
            cfg = engine.config
            if any(k.startswith("ai.") for k in changed_paths):
                confluence = getattr(engine, "confluence", None)
                if confluence:
                    confluence.obi_counts_as_confluence = cfg.ai.obi_counts_as_confluence
                    confluence.obi_weight = cfg.ai.obi_weight
                    confluence.confluence_threshold = cfg.ai.confluence_threshold
                    confluence.min_confidence = cfg.ai.min_confidence

            if any(k.startswith("risk.") for k in changed_paths):
                rm = getattr(engine, "risk_manager", None)
                if rm:
                    rm.max_risk_per_trade = cfg.risk.max_risk_per_trade
                    rm.max_daily_loss = cfg.risk.max_daily_loss
                    rm.max_daily_trades = cfg.risk.max_daily_trades
                    rm.max_position_usd = cfg.risk.max_position_usd
                    rm.max_total_exposure_pct = cfg.risk.max_total_exposure_pct
                    rm.atr_multiplier_sl = cfg.risk.atr_multiplier_sl
                    rm.atr_multiplier_tp = cfg.risk.atr_multiplier_tp
                    rm.trailing_activation_pct = cfg.risk.trailing_activation_pct
                    rm.trailing_step_pct = cfg.risk.trailing_step_pct
                    rm.breakeven_activation_pct = cfg.risk.breakeven_activation_pct
                    rm.kelly_fraction = cfg.risk.kelly_fraction
                    rm.global_cooldown_seconds_on_loss = cfg.risk.global_cooldown_seconds_on_loss

            if any(k.startswith("trading.") for k in changed_paths):
                engine.scan_interval = cfg.trading.scan_interval_seconds
                if getattr(engine, "executor", None):
                    engine.executor.max_trades_per_hour = max(
                        0, int(cfg.trading.max_trades_per_hour or 0)
                    )

        # Validation rules: (type, min, max) — None means no bound
        _SETTINGS_VALIDATORS: dict = {
            "ai.confluence_threshold": (int, 2, 8),
            "ai.min_confidence": (float, 0.45, 0.75),
            "ai.min_risk_reward_ratio": (float, 0.5, 5.0),
            "ai.obi_counts_as_confluence": (bool, None, None),
            "ai.obi_weight": (float, 0.0, 1.0),
            "ai.allow_keltner_solo": (bool, None, None),
            "ai.allow_any_solo": (bool, None, None),
            "ai.keltner_solo_min_confidence": (float, 0.50, 0.90),
            "ai.solo_min_confidence": (float, 0.50, 0.90),
            "risk.max_risk_per_trade": (float, 0.001, 0.10),
            "risk.max_daily_loss": (float, 0.01, 0.20),
            "risk.max_daily_trades": (int, 0, 2000),
            "risk.max_position_usd": (float, 10, 50000),
            "risk.max_total_exposure_pct": (float, 0.05, 1.0),
            "risk.atr_multiplier_sl": (float, 0.5, 5.0),
            "risk.atr_multiplier_tp": (float, 0.5, 10.0),
            "risk.trailing_activation_pct": (float, 0.005, 0.10),
            "risk.trailing_step_pct": (float, 0.001, 0.05),
            "risk.breakeven_activation_pct": (float, 0.005, 0.10),
            "risk.kelly_fraction": (float, 0.05, 0.50),
            "risk.global_cooldown_seconds_on_loss": (int, 0, 3600),
            "trading.scan_interval_seconds": (int, 5, 300),
            "trading.max_concurrent_positions": (int, 1, 20),
            "trading.cooldown_seconds": (int, 0, 3600),
            "trading.max_spread_pct": (float, 0.0, 0.01),
            "trading.quiet_hours_utc": (list, None, None),
            "trading.max_trades_per_hour": (int, 0, 120),
            "monitoring.auto_pause_on_stale_data": (bool, None, None),
            "monitoring.stale_data_pause_after_checks": (int, 1, 20),
            "monitoring.auto_pause_on_ws_disconnect": (bool, None, None),
            "monitoring.ws_disconnect_pause_after_seconds": (int, 10, 7200),
            "monitoring.auto_pause_on_consecutive_losses": (bool, None, None),
            "monitoring.consecutive_losses_pause_threshold": (int, 1, 20),
            "monitoring.auto_pause_on_drawdown": (bool, None, None),
            "monitoring.drawdown_pause_pct": (float, 0.1, 50.0),
            "monitoring.emergency_close_on_auto_pause": (bool, None, None),
            "ml.retrain_interval_hours": (int, 1, 720),
            "ml.min_samples": (int, 100, 100000),
        }

        @self.app.get("/api/v1/settings")
        async def get_settings(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get all tunable settings with current runtime values."""
            await _require_read_access(request, x_api_key=x_api_key)
            primary = self._get_primary_engine()
            if not primary:
                return {}
            return _read_all_settings(primary)

        @self.app.patch("/api/v1/settings")
        async def patch_settings(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Update settings at runtime and persist to config.yaml."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            engines = self._get_engines()
            if not engines:
                raise HTTPException(status_code=503, detail="Bot not running")
            primary = engines[0]

            yaml_updates: dict = {}
            changed: Set[str] = set()
            normalized_updates: Dict[str, Dict[str, Any]] = {}

            for section_key, section_values in body.items():
                if not isinstance(section_values, dict):
                    continue
                for key, value in section_values.items():
                    dotpath = f"{section_key}.{key}"
                    validator = _SETTINGS_VALIDATORS.get(dotpath)
                    if validator is None:
                        continue  # Unknown setting, skip

                    vtype, vmin, vmax = validator

                    # Type coercion + validation
                    try:
                        if vtype is bool:
                            value = _coerce_bool_setting(value, dotpath)
                        elif vtype is int:
                            value = int(value)
                        elif vtype is float:
                            value = float(value)
                        elif vtype is list:
                            if isinstance(value, str):
                                value = [int(x.strip()) for x in value.split(",") if x.strip()] if value.strip() else []
                            elif not isinstance(value, list):
                                value = list(value)
                    except (ValueError, TypeError):
                        raise HTTPException(status_code=400, detail=f"Invalid type for {dotpath}")

                    if vmin is not None and not isinstance(value, (bool, list)) and value < vmin:
                        raise HTTPException(status_code=400, detail=f"{dotpath} must be >= {vmin}")
                    if vmax is not None and not isinstance(value, (bool, list)) and value > vmax:
                        raise HTTPException(status_code=400, detail=f"{dotpath} must be <= {vmax}")

                    normalized_updates.setdefault(section_key, {})[key] = value
                    if section_key not in yaml_updates:
                        yaml_updates[section_key] = {}
                    yaml_updates[section_key][key] = value

            for eng in engines:
                cfg = eng.config
                for section_key, section_values in normalized_updates.items():
                    section_obj = getattr(cfg, section_key, None)
                    if not section_obj:
                        continue
                    for key, value in section_values.items():
                        if hasattr(section_obj, key):
                            setattr(section_obj, key, value)
                            changed.add(f"{section_key}.{key}")
                _apply_live_subsystem_updates(eng, changed)

            # Persist to config.yaml
            if yaml_updates:
                try:
                    from src.core.config import save_to_yaml
                    save_to_yaml(yaml_updates)
                except Exception as e:
                    logger.warning("Settings YAML save failed (runtime still applied)", error=repr(e))

            # Audit log
            if changed:
                for eng in engines:
                    db = getattr(eng, "db", None)
                    if not db:
                        continue
                    try:
                        await db.log_thought(
                            "system",
                            f"Settings updated via dashboard: {', '.join(sorted(changed))}",
                            severity="info",
                            tenant_id=getattr(eng, "tenant_id", "default"),
                        )
                    except Exception:
                        continue

            return _read_all_settings(primary)

        # ---- Billing (Stripe) ----
        @self.app.post("/api/v1/billing/checkout")
        async def create_checkout_session(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Create Stripe Checkout session for subscription. Body: tenant_id, success_url, cancel_url, customer_email (optional)."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            if not self._stripe_service or not self._stripe_service.enabled:
                raise HTTPException(status_code=503, detail="Billing not configured")
            tenant_id = body.get("tenant_id") or "default"
            success_url = body.get("success_url", "")
            cancel_url = body.get("cancel_url", "")
            if not success_url or not cancel_url:
                raise HTTPException(status_code=400, detail="success_url and cancel_url required")
            customer_email = body.get("customer_email")
            customer_id = None
            if self._bot_engine and self._bot_engine.db:
                tenant = await self._bot_engine.db.get_tenant(tenant_id)
                customer_id = tenant.get("stripe_customer_id") if tenant else None
            result = self._stripe_service.create_checkout_session(
                tenant_id=tenant_id,
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=customer_email,
                customer_id=customer_id,
            )
            if not result:
                raise HTTPException(status_code=500, detail="Failed to create checkout session")
            return result

        @self.app.post("/api/v1/billing/webhook")
        async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")):
            """Stripe webhook: verify signature and update tenant status. No auth (verified by Stripe signature)."""
            if not self._stripe_service or not self._stripe_service.webhook_secret:
                raise HTTPException(status_code=503, detail="Webhook not configured")
            payload = await request.body()
            if not stripe_signature:
                raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
            if not self._stripe_service.verify_webhook(payload, stripe_signature):
                raise HTTPException(status_code=400, detail="Invalid signature")
            import json as _json
            event = _json.loads(payload)
            payload_hash = hashlib.sha256(payload).hexdigest()
            event_id = str(event.get("id") or "").strip() or f"sha256:{payload_hash}"
            event_type = str(event.get("type") or "")

            primary = self._get_primary_engine()
            primary_db = primary.db if (primary and getattr(primary, "db", None)) else None
            if primary_db and await primary_db.has_processed_stripe_webhook_event(event_id):
                return {"received": True, "duplicate": True}

            await self._stripe_service.handle_webhook_event(event)
            if primary_db:
                await primary_db.mark_stripe_webhook_event_processed(
                    event_id,
                    event_type=event_type,
                    payload_hash=payload_hash,
                )
            return {"received": True, "duplicate": False}

        @self.app.get("/api/v1/tenants/{tenant_id}")
        async def get_tenant(
            request: Request,
            tenant_id: str,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get tenant by id (for dashboard / billing status)."""
            if not self._bot_engine or not self._bot_engine.db:
                raise HTTPException(status_code=503, detail="Not available")
            ctx = await _require_read_access(request, x_api_key=x_api_key)
            if ctx.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Admin required")
            resolved = await _resolve_tenant_from_credentials(
                requested_tenant_id=tenant_id,
                api_key=x_api_key,
                require_api_key=False,
            )
            tenant = await self._bot_engine.db.get_tenant(resolved)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")
            return tenant

        @self.app.post("/api/v1/alerts/test")
        async def send_test_alert(
            request: Request,
            body: dict = Body(default={}),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Send a test alert through configured notification channels."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            primary = self._get_primary_engine()
            if not primary:
                raise HTTPException(status_code=503, detail="Bot not running")

            message = str(body.get("message") or "NovaPulse test alert").strip()
            if len(message) > 500:
                message = message[:500]

            delivered = []
            failed = []

            targets = [
                ("telegram", getattr(primary, "telegram_bot", None)),
                ("discord", getattr(primary, "discord_bot", None)),
                ("slack", getattr(primary, "slack_bot", None)),
            ]
            for name, bot in targets:
                if not bot or not hasattr(bot, "send_message"):
                    continue
                try:
                    ok = await bot.send_message(f"[NovaPulse] {message}")
                    if ok is False:
                        failed.append(name)
                    else:
                        delivered.append(name)
                except Exception:
                    failed.append(name)

            if getattr(primary, "db", None):
                await primary.db.log_thought(
                    "system",
                    f"Test alert sent | delivered={','.join(delivered) or 'none'}",
                    severity="info",
                    metadata={"delivered": delivered, "failed": failed},
                    tenant_id=getattr(primary, "tenant_id", "default"),
                )

            return {"ok": True, "delivered": delivered, "failed": failed}

        # ---- Control Endpoints ----

        @self.app.post("/api/v1/control/close_all")
        async def close_all_positions(
            request: Request,
            x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Emergency close all positions (admin session + CSRF, or admin API key)."""
            ctx = await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            tenant_id = (x_tenant_id or "").strip()
            if ctx.get("role") != "admin":
                tenant_id = ctx.get("tenant_id") or _default_tenant_id()
            else:
                tenant_id = tenant_id or _default_tenant_id()
            if self._control_router:
                result = await self._control_router.close_all(
                    "api_close_all", tenant_id=tenant_id
                )
                if not result.get("ok"):
                    raise HTTPException(status_code=503, detail=result.get("error", "Bot not running"))
                return {"closed": result.get("closed", 0)}
            if not self._bot_engine:
                raise HTTPException(status_code=503, detail="Bot not running")
            count = await self._bot_engine.executor.close_all_positions(
                "api_close_all", tenant_id=tenant_id
            )
            return {"closed": count}

        @self.app.post("/api/v1/control/pause")
        async def pause_trading(
            request: Request,
            x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Pause trading (admin session + CSRF, or admin API key)."""
            ctx = await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            tenant_id = (x_tenant_id or "").strip()
            if ctx.get("role") != "admin":
                tenant_id = ctx.get("tenant_id") or _default_tenant_id()
            else:
                tenant_id = tenant_id or _default_tenant_id()
            if self._control_router:
                result = await self._control_router.pause(tenant_id=tenant_id)
                if not result.get("ok"):
                    raise HTTPException(status_code=403, detail=result.get("error", "pause denied"))
                return {"status": "paused"}
            if self._bot_engine:
                self._bot_engine._trading_paused = True
                await self._bot_engine.db.log_thought(
                    "system", "Trading PAUSED via API", severity="warning",
                    tenant_id=tenant_id,
                )
            return {"status": "paused"}

        @self.app.post("/api/v1/control/resume")
        async def resume_trading(
            request: Request,
            x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Resume trading (admin session + CSRF, or admin API key)."""
            ctx = await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            tenant_id = (x_tenant_id or "").strip()
            if ctx.get("role") != "admin":
                tenant_id = ctx.get("tenant_id") or _default_tenant_id()
            else:
                tenant_id = tenant_id or _default_tenant_id()
            if self._control_router:
                result = await self._control_router.resume(tenant_id=tenant_id)
                if not result.get("ok"):
                    raise HTTPException(status_code=403, detail=result.get("error", "resume denied"))
                return {"status": "resumed"}
            if self._bot_engine:
                self._bot_engine._trading_paused = False
                await self._bot_engine.db.log_thought(
                    "system", "Trading RESUMED via API", severity="info",
                    tenant_id=tenant_id,
                )
            return {"status": "resumed"}

        # ---- WebSocket ----

        @self.app.websocket("/ws/live")
        async def websocket_endpoint(websocket: WebSocket):
            """Real-time data streaming WebSocket."""
            requested_tenant_id = (
                websocket.query_params.get("tenant_id")
                or websocket.headers.get("x-tenant-id")
                or ""
            )
            api_key = (
                websocket.headers.get("x-api-key")
                or ""
            )
            try:
                # Cookie session (preferred for same-origin browser UI).
                tenant_id = ""
                sess_raw = (websocket.cookies.get(self._session_cookie, "") or "").strip()
                if sess_raw:
                    try:
                        sess = _serializer().loads(sess_raw, max_age=self._session_ttl_seconds)
                        if isinstance(sess, dict) and sess.get("v") == 1:
                            role = sess.get("role")
                            if role == "admin":
                                tenant_id = (requested_tenant_id or "").strip() or _default_tenant_id()
                            else:
                                tenant_id = (sess.get("tid") or "").strip() or _default_tenant_id()
                    except Exception:
                        tenant_id = ""

                # If no session, fall back to API key (or allow anonymous when disabled).
                if not tenant_id:
                    if not _require_auth_for_reads() and not api_key:
                        tenant_id = _default_tenant_id()
                    else:
                        tenant_id = await _resolve_tenant_from_credentials(
                            requested_tenant_id=requested_tenant_id,
                            api_key=api_key,
                            require_api_key=_require_auth_for_reads(),
                        )
            except HTTPException as exc:
                await websocket.accept()
                await websocket.close(
                    code=1008,
                    reason=str(exc.detail) if exc.detail else "Forbidden",
                )
                return

            # Limit concurrent WebSocket connections to prevent resource exhaustion
            if len(self._ws_connections) >= 50:
                await websocket.accept()
                await websocket.close(code=1013, reason="Too many connections")
                return

            await websocket.accept()
            self._ws_connections.add(websocket)
            logger.info("WebSocket client connected", total=len(self._ws_connections))

            try:
                while True:
                    # H13 FIX: Use cached update (built once per second)
                    now = time.time()
                    cache_time = self._ws_cache_time_by_tenant.get(tenant_id, 0.0)
                    if (tenant_id not in self._ws_cache_by_tenant) or ((now - cache_time) > 1.0):
                        self._ws_cache_by_tenant[tenant_id] = await self._build_ws_update(
                            tenant_id=tenant_id
                        )
                        self._ws_cache_time_by_tenant[tenant_id] = now
                    try:
                        await websocket.send_json(self._ws_cache_by_tenant[tenant_id])
                    except (WebSocketDisconnect, RuntimeError):
                        break
                    await asyncio.sleep(1)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug("WebSocket error", error=str(e))
            finally:
                self._ws_connections.discard(websocket)
                logger.info("WebSocket client disconnected", total=len(self._ws_connections))

    async def _build_ws_update(self, tenant_id: str = "default") -> Dict[str, Any]:
        """Build a WebSocket update payload."""
        engines = self._get_engines()
        if not engines:
            return {"type": "status", "data": {"status": "initializing"}}
        primary = self._get_primary_engine()
        if not primary or not getattr(primary, "db", None) or not getattr(primary.db, "is_initialized", False):
            return {"type": "status", "data": {"status": "initializing"}}

        # Build compact update
        try:
            stats_list: List[Dict[str, Any]] = []
            positions: List[Dict[str, Any]] = []

            # Aggregate performance stats + positions per engine
            for eng in engines:
                if not getattr(eng, "db", None):
                    continue
                stats_list.append(await eng.db.get_performance_stats(tenant_id=tenant_id))
                rows = await eng.db.get_open_trades(tenant_id=tenant_id)
                rows = [p for p in rows if abs(p.get("quantity", 0) or 0) > 0.00000001]
                fee_rate = getattr(getattr(eng, "config", None), "exchange", None)
                fee_rate = getattr(fee_rate, "taker_fee", 0.0)
                for pos in rows:
                    cp = eng.market_data.get_latest_price(pos["pair"])
                    if cp > 0:
                        notional = pos["entry_price"] * pos["quantity"]
                        if pos["side"] == "buy":
                            gross = (cp - pos["entry_price"]) * pos["quantity"]
                        else:
                            gross = (pos["entry_price"] - cp) * pos["quantity"]
                        est_entry_fee = abs(pos["entry_price"] * pos["quantity"]) * fee_rate
                        est_exit_fee = abs(cp * pos["quantity"]) * fee_rate
                        net = gross - est_entry_fee - est_exit_fee
                        pos["unrealized_pnl"] = round(net, 2)
                        pos["current_price"] = cp
                        pos["unrealized_pnl_pct"] = (
                            net / notional
                        ) if notional > 0 else 0
                    pos["exchange"] = getattr(eng, "exchange_name", "unknown")
                positions.extend(rows)

            positions.sort(key=lambda p: p.get("entry_time") or "", reverse=True)

            performance = self._aggregate_performance_stats(stats_list)

            # Thoughts (shared DB -> primary only)
            if self._engines_share_db(engines):
                thoughts = await primary.db.get_thoughts(limit=50, tenant_id=tenant_id)
            else:
                thoughts = []
                for eng in engines:
                    if not getattr(eng, "db", None):
                        continue
                    rows = await eng.db.get_thoughts(limit=50, tenant_id=tenant_id)
                    for row in rows:
                        row["exchange"] = getattr(eng, "exchange_name", "unknown")
                    thoughts.extend(rows)
                thoughts.sort(key=lambda t: t.get("timestamp") or "", reverse=True)
                thoughts = thoughts[:50]

            # Scanner (with exchange labels if needed)
            scanner_data: Dict[str, Any] = {}
            for eng in engines:
                exchange = str(getattr(eng, "exchange_name", "unknown")).lower()
                account = str(getattr(eng, "tenant_id", "default"))
                asset_class = "stock" if exchange == "stocks" else "crypto"
                for pair in getattr(eng, "pairs", []) or []:
                    label = f"{pair} ({exchange}:{account})" if len(engines) > 1 else pair
                    scanner_data[label] = {
                        "pair": pair,
                        "exchange": exchange,
                        "account_id": account,
                        "asset_class": asset_class,
                        "price": eng.market_data.get_latest_price(pair),
                        "bars": eng.market_data.get_bar_count(pair),
                        "stale": eng.market_data.is_stale(pair),
                    }

            # Risk (aggregate)
            risk = self._aggregate_risk_reports(
                [eng.risk_manager.get_risk_report() for eng in engines if getattr(eng, "risk_manager", None)]
            )

            # Strategy / algorithm stats
            if len(engines) == 1:
                strategies = engines[0].get_algorithm_stats()
            else:
                strategies = []
                for eng in engines:
                    stats_items = eng.get_algorithm_stats()
                    for s in stats_items:
                        s = dict(s)
                        s["exchange"] = getattr(eng, "exchange_name", "unknown")
                        strategies.append(s)


            # Calculate total unrealized P&L from open positions
            total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
            performance["unrealized_pnl"] = round(total_unrealized, 2)
            performance["total_equity"] = round(
                (risk.get("bankroll", 0) or 0) + total_unrealized, 2
            )

            return {
                "type": "update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "performance": performance,
                    "positions": positions,
                    "thoughts": thoughts,
                    "scanner": scanner_data,
                    "risk": risk,
                    "strategies": strategies,
                    "status": {
                        "running": any(getattr(e, "_running", False) for e in engines),
                        "paused": all(getattr(e, "_trading_paused", False) for e in engines),
                        "mode": (
                            list({getattr(e, "mode", None) for e in engines})[0]
                            if len({getattr(e, "mode", None) for e in engines}) == 1
                            else "mixed"
                        ),
                        "uptime": time.time() - min(
                            [getattr(e, "_start_time", time.time()) for e in engines]
                        ),
                        "scan_count": sum(getattr(e, "_scan_count", 0) for e in engines),
                        "ws_connected": any(
                            (getattr(e, "ws_client", None) and e.ws_client.is_connected)
                            for e in engines
                        ),
                        "exchanges": [
                            {
                                "name": getattr(e, "exchange_name", "unknown"),
                                "running": getattr(e, "_running", False),
                                "paused": getattr(e, "_trading_paused", False),
                                "ws_connected": (
                                    e.ws_client.is_connected if getattr(e, "ws_client", None) else False
                                ),
                            }
                            for e in engines
                        ],
                    }
                }
            }
        except Exception as e:
            logger.error("WebSocket update build error", error=str(e))
            # M30 FIX: Don't leak internal errors to clients
            return {"type": "error", "message": "Internal update error"}

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """Broadcast data to all connected WebSocket clients."""
        disconnected = set()
        for ws in self._ws_connections:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.add(ws)
        self._ws_connections -= disconnected
