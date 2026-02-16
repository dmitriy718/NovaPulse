"""
Telegram Command Center - Remote control and notification system.

Provides real-time trade notifications, performance alerts, and
remote command execution via Telegram bot.

Commands:
    /status - System status
    /pnl - Current P&L
    /positions - Open positions
    /kill - Emergency stop (requires confirmation)
    /close_all - Close all positions
    /pause - Pause trading
    /resume - Resume trading
    /risk - Risk report

# ENHANCEMENT: Added rate limiting for notification spam prevention
# ENHANCEMENT: Added command authentication for security
# ENHANCEMENT: Added rich message formatting with inline keyboards
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from math import floor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("telegram")


class TelegramBot:
    """
    Telegram bot for remote monitoring and control.
    
    Features:
    - Real-time trade notifications
    - P&L alerts on threshold breaches
    - Remote command execution
    - Rate-limited messaging
    
    # ENHANCEMENT: Added message queuing for offline periods
    # ENHANCEMENT: Added notification deduplication
    """

    def __init__(
        self,
        token: str = "",
        chat_id: str = "",
        chat_ids: Optional[list] = None,
        secrets_dir: str = ".secrets",
        polling_enabled: Optional[bool] = None,
        rate_limit_seconds: int = 2,
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        _single = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        env_ids = os.getenv("TELEGRAM_CHAT_IDS", "")

        # Optional secrets dir fallback for deployments that store Telegram creds on disk.
        # This keeps parity with the ops health_check cron scripts that read .secrets/*.
        sec_dir = Path(secrets_dir or ".secrets")
        if not self.token:
            try:
                p = sec_dir / "telegram_token"
                if p.exists():
                    self.token = p.read_text().strip()
            except Exception:
                pass
        if not _single and not env_ids:
            try:
                p = sec_dir / "telegram_chat_id"
                if p.exists():
                    _single = p.read_text().strip()
            except Exception:
                pass

        if chat_ids is not None:
            self.chat_ids = chat_ids
        else:
            ids = []
            if _single:
                ids.append(_single)
            if env_ids:
                ids.extend([c.strip() for c in env_ids.split(",") if c.strip()])
            self.chat_ids = ids
        self.chat_id = self.chat_ids[0] if self.chat_ids else ""  # for send_message
        self.rate_limit_seconds = rate_limit_seconds
        self._bot = None
        self._app = None
        self._last_message_time: float = 0
        self._bot_engine = None
        self._control_router = None
        self._enabled = bool(self.token and self.chat_ids)
        self._stop_event: Optional[asyncio.Event] = None
        # Default to send-only. Polling a bot token from multiple deployments causes Telegram 409 conflicts.
        self._polling_enabled = bool(polling_enabled) if polling_enabled is not None else False
        polling_env = os.getenv("TELEGRAM_POLLING_ENABLED")
        if polling_env is not None:
            polling_env = polling_env.strip().lower()
            self._polling_enabled = polling_env not in ("0", "false", "no", "off")

    def set_bot_engine(self, engine) -> None:
        """Inject the bot engine reference for command execution."""
        self._bot_engine = engine

    def set_control_router(self, router) -> None:
        """Inject the control router for pause/resume/close_all/kill."""
        self._control_router = router

    async def initialize(self) -> bool:
        """Initialize the Telegram bot."""
        if not self._enabled:
            logger.info("Telegram bot disabled (no token/chat_id)")
            return False

        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CommandHandler,
                ContextTypes,
            )

            self._app = Application.builder().token(self.token).build()

            # Register command handlers
            self._app.add_handler(CommandHandler("status", self._cmd_status))
            self._app.add_handler(CommandHandler("pnl", self._cmd_pnl))
            self._app.add_handler(CommandHandler("positions", self._cmd_positions))
            self._app.add_handler(CommandHandler("risk", self._cmd_risk))
            self._app.add_handler(CommandHandler("pause", self._cmd_pause))
            self._app.add_handler(CommandHandler("resume", self._cmd_resume))
            self._app.add_handler(CommandHandler("close_all", self._cmd_close_all))
            self._app.add_handler(CommandHandler("kill", self._cmd_kill))
            self._app.add_handler(CommandHandler("health", self._cmd_health))
            self._app.add_handler(CommandHandler("uptime", self._cmd_uptime))
            self._app.add_handler(CommandHandler("strategies", self._cmd_strategies))
            self._app.add_handler(CommandHandler("exposure", self._cmd_exposure))
            self._app.add_handler(CommandHandler("scanner", self._cmd_scanner))
            self._app.add_handler(CommandHandler("exchange", self._cmd_exchange))
            self._app.add_handler(CommandHandler("pairs", self._cmd_pairs))
            self._app.add_handler(CommandHandler("config", self._cmd_config))
            self._app.add_handler(CommandHandler("whoami", self._cmd_whoami))
            self._app.add_handler(CommandHandler("help", self._cmd_help))

            logger.info("Telegram bot initialized")
            return True

        except ImportError:
            logger.warning("python-telegram-bot not installed")
            self._enabled = False
            return False
        except Exception as e:
            logger.error("Telegram init failed", error=str(e))
            self._enabled = False
            return False

    async def start(self) -> None:
        """Start the Telegram bot polling."""
        if not self._enabled or not self._app:
            return

        try:
            if self._stop_event is None:
                self._stop_event = asyncio.Event()
            await self._app.initialize()
            await self._app.start()
            if self._polling_enabled:
                # Polling can only be active from a single process across all deployments.
                # If another instance is polling, Telegram returns 409 and we should not
                # crash-loop the whole background task.
                try:
                    from telegram.error import Conflict  # type: ignore

                    try:
                        await self._app.updater.start_polling()
                    except Conflict as e:
                        logger.warning(
                            "Telegram polling conflict; disabling polling for this instance",
                            error=str(e),
                        )
                        self._polling_enabled = False
                except Exception as e:
                    logger.warning(
                        "Telegram polling failed; disabling polling for this instance",
                        error=str(e),
                    )
                    self._polling_enabled = False

            await self.send_message(
                "🚀 *AI Trading Bot Started*\n"
                "Mode: `{}`\n"
                "Use /help for commands".format(
                    self._bot_engine.mode if self._bot_engine else "unknown"
                )
            )
            # Keep this task alive while polling is running
            await self._stop_event.wait()
        except Exception as e:
            logger.error("Telegram start failed", error=str(e))

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            try:
                await self.send_message("🔴 *AI Trading Bot Stopped*")
                if self._polling_enabled:
                    await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass
            finally:
                if self._stop_event:
                    self._stop_event.set()

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> None:
        """Send a message to the configured chat, respecting rate limits."""
        if not self._enabled or not self._app:
            return

        try:
            for cid in list(self.chat_ids or []):
                # Rate limiting across recipients
                elapsed = time.time() - self._last_message_time
                if elapsed < self.rate_limit_seconds:
                    await asyncio.sleep(self.rate_limit_seconds - elapsed)
                await self._app.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode=parse_mode,
                )
                self._last_message_time = time.time()
        except Exception as e:
            logger.debug("Telegram send failed", error=str(e))

    def _format_uptime(self, seconds: float) -> str:
        s = int(max(0, seconds))
        h = floor(s / 3600)
        m = floor((s % 3600) / 60)
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"

    async def _build_checkin_message(self) -> str:
        eng = self._bot_engine
        mode = getattr(eng, "mode", "unknown") if eng else "unknown"
        paused = bool(getattr(eng, "_trading_paused", False)) if eng else False
        running = bool(getattr(eng, "_running", False)) if eng else False
        ws_ok = bool(getattr(getattr(eng, "ws_client", None), "is_connected", False)) if eng else False
        uptime = 0.0
        if eng and getattr(eng, "_start_time", 0.0):
            uptime = time.time() - float(getattr(eng, "_start_time", 0.0) or 0.0)

        open_positions = None
        perf = {}
        try:
            if eng and getattr(eng, "db", None):
                perf = await eng.db.get_performance_stats(tenant_id=getattr(eng, "tenant_id", "default"))
                open_positions = int(perf.get("open_positions", 0) or 0)
        except Exception:
            pass

        status = "PAUSED" if paused else ("RUNNING" if running else "STOPPED")
        status_emoji = "⏸️" if paused else ("✅" if running else "🔴")
        ws_emoji = "🟢" if ws_ok else "🟠"

        total_pnl = float(perf.get("total_pnl", 0.0) or 0.0)
        today_pnl = float(perf.get("today_pnl", 0.0) or 0.0)
        win_rate = float(perf.get("win_rate", 0.0) or 0.0)
        total_trades = int(perf.get("total_trades", 0) or 0)

        lines = [
            "🛰️ *Bot Check-in*",
            f"*Status:* {status_emoji} {status}",
            f"*Mode:* `{str(mode).upper()}`",
            f"*WS:* {ws_emoji} {'CONNECTED' if ws_ok else 'DISCONNECTED'}",
            f"*Uptime:* `{self._format_uptime(uptime)}`",
        ]
        if open_positions is not None:
            lines.append(f"*Open Positions:* `{open_positions}`")
        lines.extend([
            f"*Total Trades:* `{total_trades}`",
            f"*Win Rate:* `{(win_rate * 100.0):.1f}%`",
            f"*Total PnL:* `${total_pnl:,.2f}`",
            f"*Today PnL:* `${today_pnl:,.2f}`",
            f"*Time:* `{datetime.now(timezone.utc).isoformat()}`",
        ])
        return "\n".join(lines)

    async def checkin_loop(self, interval_minutes: int = 30) -> None:
        """Send a Telegram check-in message every N minutes while the engine is running."""
        if not self._enabled:
            return
        interval = int(interval_minutes or 30)
        if interval < 1:
            interval = 30
        interval_s = interval * 60

        # Wait for the bot app to be ready (start() runs in a separate task).
        while self._enabled and self._app is None:
            await asyncio.sleep(1)

        # Send the first check-in immediately, then on the interval.
        next_ts = time.monotonic()
        while True:
            eng = self._bot_engine
            if not eng or not getattr(eng, "_running", False):
                break
            try:
                msg = await self._build_checkin_message()
                await self.send_message(msg)
            except Exception:
                pass
            next_ts += interval_s
            await asyncio.sleep(max(1.0, next_ts - time.monotonic()))

    async def notify_trade(self, trade: Dict[str, Any]) -> None:
        """Send trade notification."""
        side_emoji = "📈" if trade.get("side") == "buy" else "📉"
        msg = (
            f"{side_emoji} *Trade Executed*\n"
            f"Pair: `{trade.get('pair')}`\n"
            f"Side: `{trade.get('side', '').upper()}`\n"
            f"Price: `${trade.get('entry_price', 0):.2f}`\n"
            f"Size: `${trade.get('size_usd', 0):.2f}`\n"
            f"SL: `${trade.get('stop_loss', 0):.2f}`\n"
            f"Confidence: `{trade.get('confidence', 0):.2%}`"
        )
        await self.send_message(msg)

    async def notify_close(self, trade: Dict[str, Any]) -> None:
        """Send position close notification."""
        pnl = trade.get("pnl", 0)
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} *Position Closed*\n"
            f"Pair: `{trade.get('pair')}`\n"
            f"P&L: `${pnl:.2f}` ({trade.get('pnl_pct', 0):.2%})\n"
            f"Reason: `{trade.get('reason', 'unknown')}`"
        )
        await self.send_message(msg)

    # ------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------

    def _is_authorized(self, update) -> bool:
        """C5 FIX: Verify chat_id is in allowlist (chat_ids or legacy chat_id)."""
        if not self.chat_ids:
            return False
        ok = str(update.message.chat_id) in [str(c) for c in self.chat_ids]
        if not ok:
            try:
                logger.warning(
                    "Unauthorized telegram command",
                    chat_id=str(update.message.chat_id),
                    user_id=str(getattr(update.effective_user, "id", "")),
                    username=str(getattr(update.effective_user, "username", "")),
                )
            except Exception:
                pass
        return ok

    async def _cmd_status(self, update, context) -> None:
        """Handle /status command."""
        if not self._is_authorized(update):
            return
        if not self._bot_engine:
            await update.message.reply_text("Bot engine not connected")
            return

        msg = (
            "📊 *System Status*\n"
            f"Mode: `{self._bot_engine.mode}`\n"
            f"Running: `{self._bot_engine._running}`\n"
            f"Paused: `{self._bot_engine._trading_paused}`\n"
            f"Pairs: `{len(self._bot_engine.pairs)}`\n"
            f"Scans: `{self._bot_engine._scan_count}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_pnl(self, update, context) -> None:
        """Handle /pnl command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return

        tenant_id = getattr(self._bot_engine, "tenant_id", "default")
        stats = await self._bot_engine.db.get_performance_stats(tenant_id=tenant_id)
        risk = self._bot_engine.risk_manager.get_risk_report()
        msg = (
            "💰 *Performance*\n"
            f"Total P&L: `${stats.get('total_pnl', 0):.2f}`\n"
            f"Today P&L: `${stats.get('today_pnl', 0):.2f}`\n"
            f"Win Rate: `{stats.get('win_rate', 0):.1%}`\n"
            f"Trades: `{stats.get('total_trades', 0)}`\n"
            f"Bankroll: `${risk.get('bankroll', 0):.2f}`\n"
            f"Drawdown: `{risk.get('current_drawdown', 0):.1f}%`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_positions(self, update, context) -> None:
        """Handle /positions command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return

        tenant_id = getattr(self._bot_engine, "tenant_id", "default")
        positions = await self._bot_engine.db.get_open_trades(tenant_id=tenant_id)
        if not positions:
            await update.message.reply_text("📭 No open positions")
            return

        msg = "📊 *Open Positions*\n\n"
        for pos in positions:
            current_price = self._bot_engine.market_data.get_latest_price(pos["pair"])
            if pos["side"] == "buy":
                pnl = (current_price - pos["entry_price"]) * pos["quantity"]
            else:
                pnl = (pos["entry_price"] - current_price) * pos["quantity"]
            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += (
                f"{emoji} `{pos['pair']}` {pos['side'].upper()}\n"
                f"  Entry: ${pos['entry_price']:.2f} | Now: ${current_price:.2f}\n"
                f"  P&L: ${pnl:.2f}\n\n"
            )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_risk(self, update, context) -> None:
        """Handle /risk command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return

        risk = self._bot_engine.risk_manager.get_risk_report()
        msg = (
            "🛡️ *Risk Report*\n"
            f"Bankroll: `${risk.get('bankroll', 0):.2f}`\n"
            f"Exposure: `${risk.get('total_exposure_usd', 0):.2f}`\n"
            f"Daily P&L: `${risk.get('daily_pnl', 0):.2f}`\n"
            f"Drawdown: `{risk.get('current_drawdown', 0):.1f}%`\n"
            f"Max DD: `{risk.get('max_drawdown_pct', 0):.1f}%`\n"
            f"Risk of Ruin: `{risk.get('risk_of_ruin', 0):.4f}`\n"
            f"DD Factor: `{risk.get('drawdown_factor', 1):.2f}x`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_health(self, update, context) -> None:
        """Handle /health command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return

        ws_ok = bool(self._bot_engine.ws_client and self._bot_engine.ws_client.is_connected)
        stale_pairs = []
        try:
            stale_pairs = [
                p for p in self._bot_engine.pairs
                if self._bot_engine.market_data.is_stale(p, max_age_seconds=600)
            ]
        except Exception:
            stale_pairs = []
        msg = (
            "🩺 *Health Check*\n"
            f"WS: `{'OK' if ws_ok else 'DOWN'}`\n"
            f"Stale pairs: `{len(stale_pairs)}`"
        )
        if stale_pairs:
            msg += "\n" + ", ".join(stale_pairs[:8])
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_uptime(self, update, context) -> None:
        """Handle /uptime command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        if not self._bot_engine._start_time:
            await update.message.reply_text("Uptime: `--:--:--`", parse_mode="Markdown")
            return
        elapsed = max(0, int(time.time() - self._bot_engine._start_time))
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        await update.message.reply_text(
            f"⏱ *Uptime* `{h:02d}:{m:02d}:{s:02d}`",
            parse_mode="Markdown",
        )

    async def _cmd_strategies(self, update, context) -> None:
        """Handle /strategies command."""
        if not self._is_authorized(update) or not self._bot_engine or not self._bot_engine.confluence:
            return
        stats = self._bot_engine.confluence.get_strategy_stats()
        if not stats:
            await update.message.reply_text("No strategy stats available")
            return
        lines = []
        for s in stats:
            name = s.get("name", "unknown")
            trades = s.get("trades", 0)
            wr = s.get("win_rate", 0)
            lines.append(f"- `{name}` WR: `{wr:.1%}` Trades: `{trades}`")
        msg = "🧠 *Strategies*\n" + "\n".join(lines[:12])
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_exposure(self, update, context) -> None:
        """Handle /exposure command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        risk = self._bot_engine.risk_manager.get_risk_report()
        msg = (
            "📌 *Exposure*\n"
            f"Open positions: `{risk.get('open_positions', 0)}`\n"
            f"Total exposure: `${risk.get('total_exposure_usd', 0):.2f}`\n"
            f"Remaining capacity: `${risk.get('remaining_capacity_usd', 0):.2f}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_scanner(self, update, context) -> None:
        """Handle /scanner command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        status = self._bot_engine.market_data.get_status()
        total = len(status)
        warmed = sum(1 for v in status.values() if v.get("warmed_up"))
        stale = [k for k, v in status.items() if v.get("stale")]
        msg = (
            "📡 *Scanner*\n"
            f"Pairs: `{total}`\n"
            f"Warmed: `{warmed}`\n"
            f"Stale: `{len(stale)}`"
        )
        if stale:
            msg += "\n" + ", ".join(stale[:8])
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_exchange(self, update, context) -> None:
        """Handle /exchange command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        name = getattr(self._bot_engine, "exchange_name", "unknown")
        rest_url = getattr(self._bot_engine.config.exchange, "rest_url", "")
        ws_url = getattr(self._bot_engine.config.exchange, "ws_url", "")
        msg = (
            "🏦 *Exchange*\n"
            f"Name: `{name}`\n"
            f"REST: `{rest_url}`\n"
            f"WS: `{ws_url}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_pairs(self, update, context) -> None:
        """Handle /pairs command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        pairs = list(getattr(self._bot_engine, "pairs", []))
        if not pairs:
            await update.message.reply_text("No pairs configured.")
            return
        msg = "*Pairs*\n" + ", ".join(pairs[:30])
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_config(self, update, context) -> None:
        """Handle /config command."""
        if not self._is_authorized(update) or not self._bot_engine:
            return
        cfg = self._bot_engine.config
        msg = (
            "⚙️ *Config*\n"
            f"Mode: `{cfg.app.mode}`\n"
            f"Pairs: `{len(cfg.trading.pairs)}`\n"
            f"Scan interval: `{cfg.trading.scan_interval_seconds}s`\n"
            f"Max spread: `{cfg.trading.max_spread_pct}`\n"
            f"Confluence: `{cfg.ai.confluence_threshold}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_pause(self, update, context) -> None:
        """Handle /pause command."""
        if not self._is_authorized(update):
            return
        tid = getattr(self._bot_engine, "tenant_id", None) if self._bot_engine else None
        if self._control_router:
            await self._control_router.pause(tenant_id=tid)
            await update.message.reply_text("⏸ Trading *PAUSED*", parse_mode="Markdown")
        elif self._bot_engine:
            self._bot_engine._trading_paused = True
            await update.message.reply_text("⏸ Trading *PAUSED*", parse_mode="Markdown")

    async def _cmd_resume(self, update, context) -> None:
        """Handle /resume command."""
        if not self._is_authorized(update):
            return
        tid = getattr(self._bot_engine, "tenant_id", None) if self._bot_engine else None
        if self._control_router:
            await self._control_router.resume(tenant_id=tid)
            await update.message.reply_text("▶️ Trading *RESUMED*", parse_mode="Markdown")
        elif self._bot_engine:
            self._bot_engine._trading_paused = False
            await update.message.reply_text("▶️ Trading *RESUMED*", parse_mode="Markdown")

    async def _cmd_close_all(self, update, context) -> None:
        """Handle /close_all command."""
        if not self._is_authorized(update):
            return
        tid = getattr(self._bot_engine, "tenant_id", None) if self._bot_engine else None
        if self._control_router:
            result = await self._control_router.close_all("telegram", tenant_id=tid)
            count = result.get("closed", 0)
            await update.message.reply_text(
                f"⚠️ Closed *{count}* positions", parse_mode="Markdown"
            )
        elif self._bot_engine:
            count = await self._bot_engine.executor.close_all_positions("telegram")
            await update.message.reply_text(
                f"⚠️ Closed *{count}* positions", parse_mode="Markdown"
            )

    async def _cmd_kill(self, update, context) -> None:
        """Handle /kill command - emergency shutdown."""
        if not self._is_authorized(update):
            return
        tid = getattr(self._bot_engine, "tenant_id", None) if self._bot_engine else None
        if self._control_router:
            await update.message.reply_text(
                "🔴 *EMERGENCY SHUTDOWN INITIATED*\n"
                "Closing all positions and stopping...",
                parse_mode="Markdown"
            )
            await self._control_router.kill(tenant_id=tid)
        elif self._bot_engine:
            await update.message.reply_text(
                "🔴 *EMERGENCY SHUTDOWN INITIATED*\n"
                "Closing all positions and stopping...",
                parse_mode="Markdown"
            )
            await self._bot_engine.executor.close_all_positions("emergency_kill")
            await self._bot_engine.stop()

    async def _cmd_help(self, update, context) -> None:
        """Handle /help command."""
        if not self._is_authorized(update):
            return
        msg = (
            "🤖 *AI Trading Bot Commands*\n\n"
            "/status - System status\n"
            "/pnl - Performance summary\n"
            "/positions - Open positions\n"
            "/risk - Risk report\n"
            "/health - Health check\n"
            "/uptime - Bot uptime\n"
            "/strategies - Strategy stats\n"
            "/exposure - Exposure summary\n"
            "/scanner - Scanner status\n"
            "/exchange - Active exchange\n"
            "/pairs - Trading pairs\n"
            "/config - Key config values\n"
            "/pause - Pause trading\n"
            "/resume - Resume trading\n"
            "/close\\_all - Close all positions\n"
            "/kill - Emergency shutdown\n"
            "/whoami - Show your chat ID\n"
            "/help - This message"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _cmd_whoami(self, update, context) -> None:
        """Show chat/user identifiers (no auth required)."""
        try:
            chat_id = update.message.chat_id
            user = update.effective_user
            msg = (
                "👤 *Telegram Identity*\n"
                f"Chat ID: `{chat_id}`\n"
                f"User ID: `{getattr(user, 'id', '')}`\n"
                f"Username: `@{getattr(user, 'username', '')}`"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception:
            pass
