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
import io
import json
import os
import time
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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
        self._admin_key = os.getenv("DASHBOARD_ADMIN_KEY", "").strip()
        self._read_key = os.getenv("DASHBOARD_READ_KEY", "").strip()
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

        db = primary.db if (primary and getattr(primary, "db", None)) else None
        if require_api_key and not db:
            # Fail closed if we can't validate keys yet.
            raise HTTPException(status_code=503, detail="Tenant DB unavailable")

        mapped_tenant_id = None
        if api_key and db:
            mapped_tenant_id = await db.get_tenant_id_by_api_key(api_key)

        async def _ensure_active(tenant_id: str) -> str:
            if not db:
                return tenant_id
            tenant = await db.get_tenant(tenant_id)
            if tenant and tenant.get("status") not in ("active", "trialing"):
                raise HTTPException(status_code=403, detail="Tenant inactive")
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

        # Pass through Sharpe/Sortino from first engine (computed on full PnL series)
        for s in stats_list:
            if s and "sharpe_ratio" in s:
                agg["sharpe_ratio"] = s["sharpe_ratio"]
                agg["sortino_ratio"] = s.get("sortino_ratio", 0.0)
                break

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

    def _setup_middleware(self) -> None:
        """Configure CORS and security middleware."""
        # Restrict CORS by default; allow explicit overrides via env.
        origins_env = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
        if origins_env:
            allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
        else:
            allow_origins = ["http://localhost:8080", "http://127.0.0.1:8080"]

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
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
            env = (os.getenv("DASHBOARD_REQUIRE_AUTH_FOR_READS", "") or "").strip().lower()
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
                try:
                    return bool(_hasher().verify(self._admin_password_hash, password))
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
            if origin:
                allowed = {"http://127.0.0.1:8080", "http://localhost:8080"}
                cors_env = (os.getenv("DASHBOARD_CORS_ORIGINS", "") or "").strip()
                if cors_env:
                    allowed = {o.strip() for o in cors_env.split(",") if o.strip()}
                if origin not in allowed:
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
            primary = self._get_primary_engine()
            if primary and getattr(primary, "db", None):
                tenant_id = await primary.db.get_tenant_id_by_api_key(api_key)
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

            if api_key and primary and getattr(primary, "db", None):
                tenant_id = await primary.db.get_tenant_id_by_api_key(api_key)
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
                    f"<label>Username</label><input name='username' autocomplete='username' value='{self._admin_username}'/>"
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

            return {
                "status": "running" if running else "stopped",
                "mode": mode,
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        est_exit_fee = abs(cp * pos["quantity"]) * fee_rate
                        unrealized += (gross - est_exit_fee)

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
            if len(engines) == 1:
                return engines[0].market_data.get_status()
            scanner_data: Dict[str, Any] = {}
            seen = set()
            for eng in engines:
                for pair in getattr(eng, "pairs", []) or []:
                    label = pair
                    if label in seen or len(engines) > 1:
                        label = f"{pair} ({getattr(eng, 'exchange_name', 'unknown')})"
                    seen.add(label)
                    scanner_data[label] = {
                        "price": eng.market_data.get_latest_price(pair),
                        "bars": eng.market_data.get_bar_count(pair),
                        "stale": eng.market_data.is_stale(pair),
                    }
            return scanner_data

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

        # ---- Settings (AI / confluence options) ----
        @self.app.get("/api/v1/settings")
        async def get_settings(
            request: Request,
            x_api_key: str = Header(default="", alias="X-API-Key"),
        ):
            """Get settings used by the dashboard (e.g. Weighted Order Book)."""
            await _require_read_access(request, x_api_key=x_api_key)
            primary = self._get_primary_engine()
            if not primary:
                return {"weighted_order_book": False}
            c = getattr(primary, "confluence", None)
            return {
                "weighted_order_book": getattr(c, "obi_counts_as_confluence", False),
            }

        @self.app.patch("/api/v1/settings")
        async def patch_settings(
            request: Request,
            body: dict = Body(...),
            x_api_key: str = Header(default="", alias="X-API-Key"),
            x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
        ):
            """Update settings at runtime (e.g. Weighted Order Book). Takes effect immediately; for persistence set config.yaml and restart."""
            await _require_control_access(request, x_api_key=x_api_key, x_csrf_token=x_csrf_token)
            primary = self._get_primary_engine()
            if not primary:
                raise HTTPException(status_code=503, detail="Bot not running")
            c = getattr(primary, "confluence", None)
            if not c:
                raise HTTPException(status_code=503, detail="Confluence not available")
            if "weighted_order_book" in body:
                c.obi_counts_as_confluence = bool(body["weighted_order_book"])
            return {"weighted_order_book": c.obi_counts_as_confluence}

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
            await self._stripe_service.handle_webhook_event(event)
            return {"received": True}

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
                or websocket.query_params.get("api_key")
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
                    await websocket.send_json(self._ws_cache_by_tenant[tenant_id])
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
        if not primary or not getattr(primary, "db", None) or not primary.db._initialized:
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
                        est_exit_fee = abs(cp * pos["quantity"]) * fee_rate
                        pos["unrealized_pnl"] = round(gross - est_exit_fee, 2)
                        pos["current_price"] = cp
                        pos["unrealized_pnl_pct"] = (
                            (gross - est_exit_fee) / notional
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
            seen = set()
            for eng in engines:
                for pair in getattr(eng, "pairs", []) or []:
                    label = pair
                    if label in seen or len(engines) > 1:
                        label = f"{pair} ({getattr(eng, 'exchange_name', 'unknown')})"
                    seen.add(label)
                    scanner_data[label] = {
                        "price": eng.market_data.get_latest_price(pair),
                        "bars": eng.market_data.get_bar_count(pair),
                        "stale": eng.market_data.is_stale(pair),
                    }

            # Risk (aggregate)
            risk = self._aggregate_risk_reports(
                [eng.risk_manager.get_risk_report() for eng in engines if getattr(eng, "risk_manager", None)]
            )

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
