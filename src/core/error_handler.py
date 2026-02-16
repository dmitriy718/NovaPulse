"""
Graceful Error Handler - "Trade or Die" Error Classification System.

Classifies errors as trade-blocking vs. non-blocking so the bot can keep
trading through everything that isn't truly fatal.

Rules:
- If the bot can still place/manage trades -> CONTINUE TRADING
- Only pause/stop if exchange connection + all data sources are dead simultaneously
- On startup: if ANY subsystem fails init, log + skip it; only halt on DB or exchange REST failure
"""

from __future__ import annotations

import asyncio
import enum
import traceback
from typing import Any, Optional

from src.core.logger import get_logger

logger = get_logger("error_handler")


class ErrorSeverity(enum.Enum):
    """How badly an error affects the bot's ability to trade."""

    CRITICAL = "critical"    # Stops trading — DB down, exchange auth failure, all data dead
    DEGRADED = "degraded"    # Log + notify + continue trading
    TRANSIENT = "transient"  # Log + continue silently


# Components whose failure should NOT stop trading.
_NON_BLOCKING_COMPONENTS = frozenset({
    "telegram",
    "discord",
    "slack",
    "dashboard",
    "billing",
    "stripe",
    "ml",
    "continuous_learner",
    "predictor",
    "retrainer",
    "control_router",
})

# Components whose failure IS trade-blocking.
_CRITICAL_COMPONENTS = frozenset({
    "database",
    "db",
    "rest_client",
    "exchange_rest",
})


class GracefulErrorHandler:
    """
    Centralized error classification and handling.

    Usage::

        handler = GracefulErrorHandler(notify_fn=telegram_bot.send_message)
        severity = handler.classify_error(err, component="telegram")
        await handler.handle(err, component="telegram", context="init")
    """

    def __init__(
        self,
        notify_fn: Optional[Any] = None,
        db_log_fn: Optional[Any] = None,
    ):
        self._notify_fn = notify_fn
        self._db_log_fn = db_log_fn

    def set_notify_fn(self, fn: Any) -> None:
        self._notify_fn = fn

    def set_db_log_fn(self, fn: Any) -> None:
        self._db_log_fn = fn

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_error(
        self,
        error: BaseException,
        *,
        component: str = "",
    ) -> ErrorSeverity:
        """Classify an error by severity based on what component it came from."""
        comp = component.lower().strip()

        # Critical components -> CRITICAL
        if comp in _CRITICAL_COMPONENTS:
            return ErrorSeverity.CRITICAL

        # Non-blocking components -> DEGRADED (not CRITICAL)
        if comp in _NON_BLOCKING_COMPONENTS:
            return ErrorSeverity.DEGRADED

        # Warmup failure for a single pair is non-blocking
        if comp in ("warmup", "warmup_pair"):
            return ErrorSeverity.TRANSIENT

        # WebSocket alone is not fatal — REST can still work for trading
        if comp in ("websocket", "ws_client", "ws"):
            return ErrorSeverity.DEGRADED

        # Market data for a single pair is transient
        if comp in ("market_data",):
            return ErrorSeverity.TRANSIENT

        # Connection / timeout errors are usually transient
        if isinstance(error, (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)):
            return ErrorSeverity.TRANSIENT

        # Default: DEGRADED (safe — log + continue)
        return ErrorSeverity.DEGRADED

    # ------------------------------------------------------------------
    # Handling
    # ------------------------------------------------------------------

    async def handle(
        self,
        error: BaseException,
        *,
        component: str = "",
        context: str = "",
    ) -> ErrorSeverity:
        """
        Classify, log, and optionally notify about an error.

        Returns the severity so callers can decide what to do.
        """
        severity = self.classify_error(error, component=component)
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        tb_str = "".join(tb[-3:])  # last 3 frames for brevity

        msg = (
            f"[{severity.value.upper()}] {component or 'unknown'}"
            f"{(' / ' + context) if context else ''}: "
            f"{type(error).__name__}: {error}"
        )

        if severity == ErrorSeverity.CRITICAL:
            logger.critical(msg, traceback=tb_str)
        elif severity == ErrorSeverity.DEGRADED:
            logger.warning(msg, traceback=tb_str)
        else:
            logger.info(msg)

        # Persist to DB when available
        if self._db_log_fn:
            try:
                sev_map = {
                    ErrorSeverity.CRITICAL: "critical",
                    ErrorSeverity.DEGRADED: "warning",
                    ErrorSeverity.TRANSIENT: "info",
                }
                await self._db_log_fn(
                    "system",
                    msg,
                    severity=sev_map.get(severity, "info"),
                )
            except Exception:
                pass

        # Notify operator on CRITICAL or DEGRADED
        if severity in (ErrorSeverity.CRITICAL, ErrorSeverity.DEGRADED) and self._notify_fn:
            try:
                await self._notify_fn(msg)
            except Exception:
                pass

        return severity
