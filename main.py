#!/usr/bin/env python3
"""
AI Trading Bot - Main Entry Point

H5 FIX: Single clean lifecycle - main.py owns init/run/shutdown.
L4 FIX: preflight_checks returns False on critical failures.
L5 FIX: traceback imported at module level.
L2 FIX: Uses get_running_loop() instead of deprecated get_event_loop().
"""

from __future__ import annotations

import asyncio
import os
import signal as sig
import sys
import time
import traceback
from pathlib import Path
import random

_INSTANCE_LOCK_FD: int | None = None


def _acquire_instance_lock() -> bool:
    """
    Best-effort single-instance lock to prevent duplicate bots on the same host/volume.

    This protects the SQLite DB and prevents double-trading if the bot is accidentally
    started twice (cron, shell, deploy scripts, etc.).
    """
    # Only available on POSIX platforms.
    try:
        import fcntl  # type: ignore
    except Exception:
        return True

    lock_path = os.getenv("INSTANCE_LOCK_PATH", "data/instance.lock").strip() or "data/instance.lock"
    lock_file = Path(lock_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            existing = os.read(fd, 64).decode("utf-8", "ignore").strip()
        except Exception:
            existing = ""
        msg = f"[FATAL] Another bot instance is already running (lock: {lock_file})."
        if existing:
            msg += f" (pid: {existing})"
        print(msg)
        os.close(fd)
        return False
    except Exception:
        # If we can't lock for an unexpected reason, fail closed.
        print(f"[FATAL] Unable to acquire instance lock at {lock_file}.")
        os.close(fd)
        return False

    # Record current PID for operators; keep FD open for the life of the process.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
    except Exception:
        pass
    global _INSTANCE_LOCK_FD
    _INSTANCE_LOCK_FD = fd
    return True


def _running_in_docker() -> bool:
    # Standard marker created by Docker; also allow explicit override.
    return Path("/.dockerenv").exists() or os.getenv("RUNNING_IN_DOCKER", "").strip() == "1"

def preflight_checks() -> bool:
    """Run pre-flight system checks before startup."""
    ok = True

    # Create required directories
    for directory in ["data", "logs", "models", "config"]:
        Path(directory).mkdir(parents=True, exist_ok=True)

    # Warn about missing config
    if not Path("config/config.yaml").exists():
        print("[WARN] config/config.yaml not found, using defaults")

    if not _acquire_instance_lock():
        ok = False

    # Check .env exists (developer/local convenience).
    # In Docker deployments, `docker compose` injects env vars and `.env` is not
    # necessarily available inside the container filesystem.
    if not _running_in_docker():
        if not Path(".env").exists():
            if Path(".env.example").exists():
                print("[WARN] No .env file. Copy .env.example -> .env and configure.")
                ok = False
            else:
                print("[WARN] No .env or .env.example found")
                ok = False

    return ok


async def run_bot():
    """Initialize and run the bot engine with dashboard server."""
    import uvicorn
    from src.api.server import DashboardServer
    from src.core.config import ConfigManager, load_config_with_overrides
    from src.core.engine import BotEngine
    from src.core.logger import get_logger
    from src.core.runtime_safety import install_asyncio_exception_handler
    from src.core.error_handler import ErrorSeverity, GracefulErrorHandler
    from src.core.multi_engine import (
        MultiControlRouter,
        MultiEngineHub,
        resolve_db_path,
        resolve_exchange_names,
    )

    logger = get_logger("main")
    default_exchange = ConfigManager().config.exchange.name
    exchange_names = resolve_exchange_names(default_exchange)
    multi = len(exchange_names) > 1

    shutdown_event = asyncio.Event()

    async def _run_with_restart(
        engine,
        name,
        coro_factory,
        *,
        critical: bool = False,
        pause_after_failures: int = 3,
        reset_failures_after_seconds: int = 600,
        base_delay: int = 2,
        max_delay: int = 30,
    ):
        failures = 0
        while engine._running:
            started = time.time()
            try:
                await coro_factory()
                if engine._running:
                    failures += 1
                    logger.warning(
                        "Background task exited unexpectedly",
                        task=name,
                        failures=failures,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                failures += 1
                logger.error(
                    "Background task failed",
                    task=name,
                    error=repr(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc(),
                    failures=failures,
                )

            # If a task survived for a while before failing, don't keep exponential backoff forever.
            ran_for = max(0.0, time.time() - started)
            if ran_for >= float(reset_failures_after_seconds or 0):
                failures = 0

            # Non-destructive handling: if critical tasks repeatedly error, pause trading instead of crashing.
            if (
                critical
                and failures >= int(pause_after_failures or 0)
                and getattr(engine, "_running", False)
                and not getattr(engine, "_trading_paused", False)
            ):
                try:
                    await engine._auto_pause_trading(
                        "task_failures",
                        detail=f"{name} failed {failures}x; trading paused until resume",
                    )
                except Exception:
                    pass
            if engine._running:
                delay = min(max_delay, base_delay * (2 ** min(failures - 1, 5)))
                delay = float(delay) + random.random()  # jitter
                try:
                    await engine.db.log_thought(
                        "system",
                        f"Task {name} restarted after error (retry in {delay}s)",
                        severity="warning",
                        tenant_id=engine.tenant_id,
                    )
                except Exception:
                    pass
                await asyncio.sleep(delay)

    if not multi:
        engine = BotEngine()

        # Phase 1: Initialize all subsystems
        await engine.initialize()
        await engine.warmup()

        # Phase 2: Start uvicorn dashboard (without its own signal handlers)
        uvi_config = uvicorn.Config(
            app=engine.dashboard.app,
            host=engine.config.dashboard.host,
            port=engine.config.dashboard.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(uvi_config)
        server.install_signal_handlers = lambda: None

        # Phase 3: Setup state and signal handling
        engine._running = True
        engine._start_time = time.time()

        def _request_shutdown():
            engine._running = False
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        install_asyncio_exception_handler(loop, logger)
        for s in (sig.SIGINT, sig.SIGTERM):
            try:
                loop.add_signal_handler(s, _request_shutdown)
            except NotImplementedError:
                sig.signal(s, lambda *_: _request_shutdown())

        await engine.db.log_thought(
            "system",
            "Bot engine STARTED - All systems operational",
            severity="info",
            tenant_id=engine.tenant_id,
        )

        # Phase 4: Start background tasks
        engine._tasks = [
            asyncio.create_task(_run_with_restart(engine, "scan_loop", engine._main_scan_loop, critical=True)),
            asyncio.create_task(_run_with_restart(engine, "position_loop", engine._position_management_loop, critical=True)),
            asyncio.create_task(_run_with_restart(engine, "ws_loop", engine._ws_data_loop, critical=True)),
            asyncio.create_task(_run_with_restart(engine, "health_monitor", engine._health_monitor, critical=True)),
            asyncio.create_task(_run_with_restart(engine, "cleanup_loop", engine._cleanup_loop)),
            asyncio.create_task(_run_with_restart(engine, "auto_retrainer", engine.retrainer.run)),
        ]
        if getattr(engine, "exchange_name", "") == "coinbase":
            engine._tasks.append(
                asyncio.create_task(_run_with_restart(engine, "rest_candles", engine._rest_candle_poll_loop, critical=True))
            )
        if engine.telegram_bot:
            engine._tasks.append(
                asyncio.create_task(_run_with_restart(engine, "telegram_bot", engine.telegram_bot.start))
            )
            try:
                tcfg = getattr(getattr(engine.config, "control", None), "telegram", None)
                if tcfg and getattr(tcfg, "send_checkins", False):
                    interval = int(getattr(tcfg, "checkin_interval_minutes", 30) or 30)
                    engine._tasks.append(
                        asyncio.create_task(
                            _run_with_restart(
                                engine,
                                "telegram_checkins",
                                lambda: engine.telegram_bot.checkin_loop(interval_minutes=interval),
                            )
                        )
                    )
            except Exception:
                pass
        # Keep the dashboard alive, but never let it take down trading.
        server_holder = {"server": server}

        async def _dashboard_serve_once():
            # Recreate server on each attempt to avoid internal "should_exit" residue.
            ucfg = uvicorn.Config(
                app=engine.dashboard.app,
                host=engine.config.dashboard.host,
                port=engine.config.dashboard.port,
                log_level="warning",
                access_log=False,
            )
            srv = uvicorn.Server(ucfg)
            srv.install_signal_handlers = lambda: None
            server_holder["server"] = srv
            await srv.serve()

        server_task = asyncio.create_task(_run_with_restart(engine, "dashboard_server", _dashboard_serve_once))

        # Phase 5: Wait for shutdown signal
        await shutdown_event.wait()

        # Phase 6: Graceful shutdown
        logger = get_logger("main")
        logger.info("Shutdown signal received, cleaning up...")
        await engine.stop()
        try:
            cur = server_holder.get("server")
            if cur:
                cur.should_exit = True
        except Exception:
            pass

        try:
            await asyncio.wait_for(server_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass
        return

    # ---- Multi-exchange mode ----
    engines = []
    base_db_path = os.getenv("DB_PATH", ConfigManager().config.app.db_path or "data/trading.db")
    start_time = time.time()

    for name in exchange_names:
        db_path = resolve_db_path(base_db_path, name, multi=True)
        overrides = {
            "exchange": {"name": name},
            "app": {"db_path": db_path},
        }
        cfg = load_config_with_overrides(overrides=overrides)
        eng = BotEngine(config_override=cfg, enable_dashboard=False)
        await eng.initialize()
        await eng.warmup()
        eng._running = True
        eng._start_time = start_time
        engines.append(eng)

        if eng.db:
            await eng.db.log_thought(
                "system",
                f"Bot engine STARTED ({name}) - All systems operational",
                severity="info",
                tenant_id=eng.tenant_id,
            )

    hub = MultiEngineHub(engines)
    dashboard = DashboardServer()
    dashboard.set_bot_engine(hub)
    dashboard.set_control_router(MultiControlRouter([e.control_router for e in engines]))

    uvi_config = uvicorn.Config(
        app=dashboard.app,
        host=engines[0].config.dashboard.host,
        port=engines[0].config.dashboard.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uvi_config)
    server.install_signal_handlers = lambda: None

    def _request_shutdown_multi():
        for eng in engines:
            eng._running = False
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    install_asyncio_exception_handler(loop, logger)
    for s in (sig.SIGINT, sig.SIGTERM):
        try:
            loop.add_signal_handler(s, _request_shutdown_multi)
        except NotImplementedError:
            sig.signal(s, lambda *_: _request_shutdown_multi())

    all_tasks = []
    for eng in engines:
        eng._tasks = [
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:scan_loop", eng._main_scan_loop)),
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:position_loop", eng._position_management_loop)),
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:ws_loop", eng._ws_data_loop)),
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:health_monitor", eng._health_monitor)),
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:cleanup_loop", eng._cleanup_loop)),
            asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:auto_retrainer", eng.retrainer.run)),
        ]
        if getattr(eng, "exchange_name", "") == "coinbase":
            eng._tasks.append(
                asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:rest_candles", eng._rest_candle_poll_loop))
            )
        if eng.telegram_bot:
            eng._tasks.append(
                asyncio.create_task(_run_with_restart(eng, f"{eng.exchange_name}:telegram_bot", eng.telegram_bot.start))
            )
        all_tasks.extend(eng._tasks)

    # Start a single check-in loop (avoid duplicate check-ins in multi-exchange mode).
    try:
        primary = engines[0] if engines else None
        tcfg = getattr(getattr(primary.config, "control", None), "telegram", None) if primary else None
        if primary and primary.telegram_bot and tcfg and getattr(tcfg, "send_checkins", False):
            interval = int(getattr(tcfg, "checkin_interval_minutes", 30) or 30)
            primary._tasks.append(
                asyncio.create_task(
                    _run_with_restart(
                        primary,
                        f"{primary.exchange_name}:telegram_checkins",
                        lambda: primary.telegram_bot.checkin_loop(interval_minutes=interval),
                    )
                )
            )
    except Exception:
        pass

    # Keep the dashboard alive, but never let it take down trading.
    server_holder = {"server": server}

    async def _dashboard_serve_once_multi():
        ucfg = uvicorn.Config(
            app=dashboard.app,
            host=engines[0].config.dashboard.host,
            port=engines[0].config.dashboard.port,
            log_level="warning",
            access_log=False,
        )
        srv = uvicorn.Server(ucfg)
        srv.install_signal_handlers = lambda: None
        server_holder["server"] = srv
        await srv.serve()

    primary_engine = engines[0] if engines else None
    if primary_engine:
        server_task = asyncio.create_task(
            _run_with_restart(primary_engine, "dashboard_server", _dashboard_serve_once_multi)
        )
    else:
        server_task = asyncio.create_task(server.serve())

    await shutdown_event.wait()

    logger = get_logger("main")
    logger.info("Shutdown signal received, cleaning up...")
    for eng in engines:
        await eng.stop()
    try:
        cur = server_holder.get("server")
        if cur:
            cur.should_exit = True
    except Exception:
        pass

    try:
        await asyncio.wait_for(server_task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
        pass


def main():
    """Main entry point."""
    # The project previously blocked 3.13, but current deployments run 3.13.x.
    # Keep a conservative guard against future majors.
    if sys.version_info >= (3, 14):
        print(
            "[FATAL] Python 3.14+ is not supported yet. "
            "Use Python 3.11, 3.12, or 3.13."
        )
        sys.exit(1)

    from src.core.config import ConfigManager
    from src.core.logger import get_logger, setup_logging
    from src.core.runtime_safety import install_global_exception_handlers

    if not preflight_checks():
        sys.exit(1)

    # Setup logging before any engine imports use loggers
    config = ConfigManager()
    setup_logging(
        log_level=config.config.app.log_level,
        log_dir="logs",
    )

    logger = get_logger("main")
    install_global_exception_handlers(logger, log_dir="logs")
    from src import __version__
    logger.info(
        "Starting AI Trading Bot",
        version=__version__,
        python=sys.version,
        mode=config.config.app.mode,
    )

    print(f"""
    ╔══════════════════════════════════════════════╗
    ║        AI CRYPTO TRADING BOT v{__version__}          ║
    ║   Multi-Strategy • AI-Powered • Self-Learning ║
    ╚══════════════════════════════════════════════╝
    """)

    # Top-level supervisor: keep the process alive on unexpected fatal exceptions.
    # Cap restarts to prevent resource exhaustion if the bot can't start.
    failures = 0
    max_failures = 10
    base_delay = 2.0
    max_delay = 60.0
    while failures < max_failures:
        try:
            asyncio.run(run_bot())
            return
        except KeyboardInterrupt:
            logger.info("Shutdown requested via keyboard interrupt")
            return
        except SystemExit:
            raise
        except Exception as e:
            failures += 1
            delay = min(max_delay, base_delay * (2 ** min(failures - 1, 6)))
            delay = float(delay) + random.random()
            traceback.print_exc()
            logger.critical(
                "Fatal runtime error; restarting bot",
                error=repr(e),
                error_type=type(e).__name__,
                failures=failures,
                max_failures=max_failures,
                restart_in_seconds=round(delay, 2),
            )
            time.sleep(delay)

    logger.critical(
        "Max restart attempts reached, shutting down",
        failures=failures,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
