"""
Structured Logging System - Production-grade logging with multiple outputs.

Provides structured JSON logging with context injection, correlation IDs,
and automatic performance measurement.

# ENHANCEMENT: Added correlation ID tracking across async operations
# ENHANCEMENT: Added log sampling for high-frequency events
# ENHANCEMENT: Added automatic sensitive data masking
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import structlog


# ---------------------------------------------------------------------------
# Sensitive Data Filter
# ---------------------------------------------------------------------------

_TELEGRAM_BOT_TOKEN_RE = re.compile(r"(bot\d+):([A-Za-z0-9_-]{20,})")
_TELEGRAM_API_URL_RE = re.compile(r"(https?://api\.telegram\.org/)(bot\d+):([A-Za-z0-9_-]{20,})")

def _scrub_string(s: str) -> str:
    # Redact Telegram bot tokens if they appear in URLs, tracebacks, or exception strings.
    s = _TELEGRAM_API_URL_RE.sub(r"\1\2:<redacted>", s)
    s = _TELEGRAM_BOT_TOKEN_RE.sub(r"\1:<redacted>", s)
    return s

def _scrub_value(v: Any) -> Any:
    if isinstance(v, str):
        return _scrub_string(v)
    if isinstance(v, dict):
        return {k: _scrub_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        t = [_scrub_value(x) for x in v]
        return tuple(t) if isinstance(v, tuple) else t
    return v

def _mask_sensitive(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive data in log output (API keys, passwords, etc.)."""
    sensitive_keys = {"api_key", "api_secret", "password", "token", "secret"}
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            value = str(event_dict[key])
            if len(value) > 8:
                event_dict[key] = value[:4] + "****" + value[-4:]
            else:
                event_dict[key] = "****"
        else:
            event_dict[key] = _scrub_value(event_dict[key])
    return event_dict


# ---------------------------------------------------------------------------
# Performance Timer Processor
# ---------------------------------------------------------------------------

class PerformanceTimer:
    """Context manager for measuring and logging operation duration."""

    def __init__(self, logger: Any, operation: str, **kwargs):
        self.logger = logger
        self.operation = operation
        self.kwargs = kwargs
        self.start_time: float = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self.start_time) * 1000  # ms
        if exc_type:
            self.logger.error(
                f"{self.operation} failed",
                duration_ms=round(elapsed, 2),
                error=str(exc_val),
                **self.kwargs
            )
        else:
            level = "warning" if elapsed > 1000 else "debug"
            getattr(self.logger, level)(
                f"{self.operation} completed",
                duration_ms=round(elapsed, 2),
                **self.kwargs
            )
        return False


# ---------------------------------------------------------------------------
# Logger Setup
# ---------------------------------------------------------------------------

def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    json_output: bool = False
) -> None:
    """
    Configure the structured logging system.
    
    Sets up:
    - Console output with colors (or JSON for production)
    - File output with rotation
    - Error-level separate file
    - Structured context injection
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Standard library logging config
    level = getattr(logging, log_level.upper(), logging.INFO)

    # M7 FIX: Rotating file handlers to prevent disk fill
    from logging.handlers import RotatingFileHandler

    main_handler = RotatingFileHandler(
        log_path / "trading_bot.log", encoding="utf-8",
        maxBytes=50 * 1024 * 1024, backupCount=5,  # 50MB, 5 backups
    )
    main_handler.setLevel(level)

    error_handler = RotatingFileHandler(
        log_path / "errors.log", encoding="utf-8",
        maxBytes=10 * 1024 * 1024, backupCount=3,  # 10MB, 3 backups
    )
    error_handler.setLevel(logging.ERROR)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Close and remove existing handlers to avoid duplicates and FD leaks
    for h in root_logger.handlers[:]:
        h.close()
        root_logger.removeHandler(h)
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # Prevent third-party libs from logging sensitive URLs/headers at INFO.
    # Example: httpx can log full request URLs, which for Telegram includes the bot token.
    for noisy in (
        "httpx",
        "httpcore",
        "websockets",
        "asyncio",
        "uvicorn.access",
        # Elasticsearch transport logs each request at INFO; keep warnings/errors only.
        "elastic_transport",
        "elastic_transport.transport",
        "elasticsearch",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Structlog configuration
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _mask_sensitive,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=40,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Set formatter for handlers
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


def get_logger(name: str = "trading_bot") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance with the given name."""
    return structlog.get_logger(name)


def log_performance(logger: Any, operation: str, **kwargs) -> PerformanceTimer:
    """Create a performance timing context manager."""
    return PerformanceTimer(logger, operation, **kwargs)


# ---------------------------------------------------------------------------
# Telegram Alert Handler - forwards ERROR+ logs to Telegram
# ---------------------------------------------------------------------------

class TelegramAlertHandler(logging.Handler):
    """
    Logging handler that forwards ERROR and CRITICAL log messages to Telegram.

    Features:
    - Rate-limited to prevent spam (configurable min interval)
    - Batches multiple errors within a window into a single message
    - Async-safe: queues messages for a background task to send
    - Truncates long messages to fit Telegram's 4096 char limit
    - Suppresses its own errors to avoid infinite recursion
    """

    MAX_MESSAGE_LEN = 4000  # Telegram limit is 4096; leave room for wrapper
    MAX_QUEUE_SIZE = 100

    def __init__(
        self,
        telegram_bot: Any,
        min_interval_seconds: float = 10.0,
        level: int = logging.ERROR,
    ):
        super().__init__(level)
        self._telegram_bot = telegram_bot
        self._min_interval = min_interval_seconds
        self._queue: list = []
        self._last_send_time: float = 0.0
        self._flush_task: Optional[Any] = None
        self._loop: Optional[Any] = None

    def emit(self, record: logging.LogRecord) -> None:
        """Queue a log record for Telegram delivery."""
        try:
            # Don't forward our own telegram send errors (avoid infinite loop)
            if record.name in ("telegram", "httpx", "httpcore"):
                return

            msg = self.format(record) if self.formatter else record.getMessage()
            # Strip ANSI color codes that structlog console renderer adds
            msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
            if len(msg) > 300:
                msg = msg[:300] + "..."

            self._queue.append(msg)

            # Cap queue size to prevent memory issues
            if len(self._queue) > self.MAX_QUEUE_SIZE:
                self._queue = self._queue[-self.MAX_QUEUE_SIZE:]

            # Schedule a flush if not already pending
            self._schedule_flush()
        except Exception:
            # Never let the handler itself crash the application
            pass

    def _schedule_flush(self) -> None:
        """Schedule an async flush of the message queue."""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = loop.create_task(self._delayed_flush())
        except RuntimeError:
            # No running event loop - can't send async
            pass

    async def _delayed_flush(self) -> None:
        """Wait for the rate limit window, then flush all queued messages."""
        import asyncio
        try:
            # Wait for the rate limit interval
            elapsed = time.time() - self._last_send_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

            if not self._queue:
                return

            # Drain the queue
            messages = self._queue[:]
            self._queue.clear()

            # Build a batched Telegram message
            count = len(messages)
            if count == 1:
                header = "🚨 *Error Alert*"
            else:
                header = f"🚨 *{count} Error Alerts*"

            body = "\n\n".join(f"```\n{m}\n```" for m in messages[:10])
            if count > 10:
                body += f"\n\n_...and {count - 10} more errors_"

            full_msg = f"{header}\n\n{body}"
            if len(full_msg) > self.MAX_MESSAGE_LEN:
                full_msg = full_msg[:self.MAX_MESSAGE_LEN] + "\n```\n_...truncated_"

            self._last_send_time = time.time()
            await self._telegram_bot.send_message(full_msg)
        except Exception:
            # Swallow send failures silently
            pass


# Global reference so it can be attached after TelegramBot is initialized
_telegram_alert_handler: Optional[TelegramAlertHandler] = None


def attach_telegram_alerts(telegram_bot: Any, min_interval: float = 10.0) -> None:
    """
    Attach a TelegramAlertHandler to the root logger so all ERROR+ logs
    are forwarded to Telegram.

    Call this after the TelegramBot is initialized and ready to send messages.
    """
    global _telegram_alert_handler

    # Remove previous handler if re-attaching
    if _telegram_alert_handler is not None:
        logging.getLogger().removeHandler(_telegram_alert_handler)

    _telegram_alert_handler = TelegramAlertHandler(
        telegram_bot,
        min_interval_seconds=min_interval,
        level=logging.ERROR,
    )
    logging.getLogger().addHandler(_telegram_alert_handler)


# ---------------------------------------------------------------------------
# Dashboard Alert Handler - forwards WARNING+ logs to dashboard alert panel
# ---------------------------------------------------------------------------

# Components whose WARNING+ logs are forwarded to the dashboard alert panel.
_DASHBOARD_ALERT_COMPONENTS = {"executor", "risk_manager", "engine", "exchange", "market_data"}


class DashboardAlertHandler(logging.Handler):
    """
    Logging handler that forwards WARNING+ log messages from key components
    to the dashboard server's alert ring buffer.

    Features:
    - Filters to key components only (executor, risk_manager, engine, exchange, market_data)
    - Rate-limited: max 1 alert per unique message per 30 seconds
    - Strips ANSI color codes from formatted messages
    """

    RATE_LIMIT_SECONDS = 30.0

    def __init__(self, dashboard_server: Any, level: int = logging.WARNING):
        super().__init__(level)
        self._dashboard_server = dashboard_server
        self._recent: Dict[str, float] = {}  # message -> last_emit_time

    def emit(self, record: logging.LogRecord) -> None:
        """Push a log record to the dashboard alert ring buffer."""
        try:
            # Only forward logs from key components
            if record.name not in _DASHBOARD_ALERT_COMPONENTS:
                return

            msg = self.format(record) if self.formatter else record.getMessage()
            # Strip ANSI color codes that structlog console renderer adds
            msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
            if len(msg) > 500:
                msg = msg[:500] + "..."

            # Rate limit: max 1 per unique message per 30 seconds
            now = time.time()
            dedup_key = f"{record.name}:{record.msg}"
            last_time = self._recent.get(dedup_key, 0.0)
            if now - last_time < self.RATE_LIMIT_SECONDS:
                return
            self._recent[dedup_key] = now

            # Purge stale dedup entries periodically (keep dict bounded)
            if len(self._recent) > 500:
                cutoff = now - self.RATE_LIMIT_SECONDS
                self._recent = {k: v for k, v in self._recent.items() if v > cutoff}

            # Map log level to alert level
            if record.levelno >= logging.CRITICAL:
                level = "critical"
            elif record.levelno >= logging.ERROR:
                level = "error"
            else:
                level = "warning"

            self._dashboard_server.push_alert(
                level=level,
                component=record.name,
                message=msg,
            )
        except Exception:
            # Never let the handler itself crash the application
            pass


# Global reference so it can be attached after DashboardServer is initialized
_dashboard_alert_handler: Optional[DashboardAlertHandler] = None


def attach_dashboard_alerts(dashboard_server: Any) -> None:
    """
    Attach a DashboardAlertHandler to the root logger so all WARNING+ logs
    from key components are forwarded to the dashboard alert panel.

    Call this after the DashboardServer is initialized.
    """
    global _dashboard_alert_handler

    # Remove previous handler if re-attaching
    if _dashboard_alert_handler is not None:
        logging.getLogger().removeHandler(_dashboard_alert_handler)

    _dashboard_alert_handler = DashboardAlertHandler(
        dashboard_server,
        level=logging.WARNING,
    )
    logging.getLogger().addHandler(_dashboard_alert_handler)
