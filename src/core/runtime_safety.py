"""
Runtime Safety Hooks

Installs best-effort global exception handlers and asyncio loop handlers so that:
- unhandled exceptions are logged with tracebacks (instead of disappearing)
- unexpected exceptions in threads are captured
- asyncio "exception was never retrieved" contexts are logged

This is intentionally non-fatal: handlers should never raise.
"""

from __future__ import annotations

import asyncio
import faulthandler
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Optional


_FAULT_FH = None  # keep fault log handle alive for the process lifetime


def _fmt_tb(exc: BaseException) -> str:
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return "traceback_unavailable"


def install_global_exception_handlers(logger: Any, log_dir: str = "logs") -> None:
    """
    Install sys/thread exception hooks + faulthandler.

    Note: This does not prevent process exit on truly fatal errors (segfault, OOM),
    but it makes failures observable and easier to debug in production.
    """
    # faulthandler: dump Python tracebacks on fatal signals (segfault, etc.)
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fault_path = Path(log_dir) / "faults.log"
        # Keep the file handle open to ensure writes even late in shutdown.
        global _FAULT_FH
        _FAULT_FH = open(fault_path, "a", encoding="utf-8")
        fh = _FAULT_FH
        faulthandler.enable(file=fh, all_threads=True)
        # Also dump on SIGUSR1 if available (manual debug trigger).
        if hasattr(signal := __import__("signal"), "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=fh, all_threads=True)
    except Exception:
        pass

    # sys.excepthook: last-resort logging for uncaught exceptions on main thread
    prev_hook: Optional[Callable[..., Any]] = getattr(sys, "excepthook", None)

    def _sys_hook(exctype, value, tb):  # type: ignore[no-untyped-def]
        try:
            if isinstance(value, BaseException):
                logger.critical(
                    "Unhandled exception (sys.excepthook)",
                    error_type=getattr(exctype, "__name__", str(exctype)),
                    error=str(value),
                    traceback="".join(traceback.format_exception(exctype, value, tb)),
                )
            else:
                logger.critical(
                    "Unhandled exception (sys.excepthook)",
                    error_type=getattr(exctype, "__name__", str(exctype)),
                    error=repr(value),
                )
        except Exception:
            pass
        try:
            if prev_hook and prev_hook is not _sys_hook:
                prev_hook(exctype, value, tb)  # type: ignore[misc]
        except Exception:
            pass

    sys.excepthook = _sys_hook  # type: ignore[assignment]

    # threading.excepthook: log uncaught exceptions in threads (Python 3.8+)
    prev_thook = getattr(threading, "excepthook", None)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        try:
            exc = args.exc_value
            logger.error(
                "Unhandled exception in thread",
                thread=getattr(args.thread, "name", "unknown"),
                error_type=type(exc).__name__ if isinstance(exc, BaseException) else "unknown",
                error=str(exc) if isinstance(exc, BaseException) else repr(exc),
                traceback=_fmt_tb(exc) if isinstance(exc, BaseException) else None,
            )
        except Exception:
            pass
        try:
            if prev_thook and prev_thook is not _thread_hook:
                prev_thook(args)  # type: ignore[misc]
        except Exception:
            pass

    if prev_thook is not None:
        threading.excepthook = _thread_hook  # type: ignore[assignment]


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop, logger: Any) -> None:
    """
    Ensure all unhandled asyncio exceptions are logged.

    This covers cases like:
    - "Task exception was never retrieved"
    - exceptions in callbacks/transport handlers
    """
    def _handler(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        try:
            msg = context.get("message", "asyncio_exception")
            exc = context.get("exception")
            if isinstance(exc, BaseException):
                logger.error(
                    "Asyncio exception",
                    message=msg,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    traceback=_fmt_tb(exc),
                )
            else:
                # Some contexts provide no exception object; still log what we have.
                safe_ctx = {k: repr(v) for k, v in context.items() if k not in ("handle", "future", "task")}
                logger.error("Asyncio exception", message=msg, context=safe_ctx)
        except Exception:
            pass

    try:
        loop.set_exception_handler(_handler)
    except Exception:
        pass
