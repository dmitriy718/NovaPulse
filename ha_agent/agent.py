"""Core autonomous agent engine — orchestrates probes, incidents, and notifications."""

from __future__ import annotations

import asyncio
import logging
import random
import signal
import time
from typing import Any

import aiohttp

from ha_agent import __agent_name__, __version__
from ha_agent.config import AgentConfig, NotificationChannelConfig, load_config
from ha_agent.incidents.manager import IncidentManager
from ha_agent.incidents.remediation import RemediationEngine
from ha_agent.models import Incident, MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.notifications.base import NotificationDispatcher
from ha_agent.notifications.discord import DiscordNotifier
from ha_agent.notifications.email_notifier import EmailNotifier
from ha_agent.notifications.pagerduty import PagerDutyNotifier
from ha_agent.notifications.slack import SlackNotifier
from ha_agent.notifications.webhook import WebhookNotifier
from ha_agent.probes.base import BaseProbe
from ha_agent.probes.custom_probe import CustomProbe
from ha_agent.probes.dns_probe import DNSProbe
from ha_agent.probes.docker_probe import DockerProbe
from ha_agent.probes.http_probe import HTTPProbe
from ha_agent.probes.icmp_probe import ICMPProbe
from ha_agent.probes.process_probe import ProcessProbe
from ha_agent.probes.ssl_probe import SSLProbe
from ha_agent.probes.tcp_probe import TCPProbe
from ha_agent.storage.database import Database
from ha_agent.storage.metrics import MetricsCollector
from ha_agent.utils.logging_setup import setup_logging

logger = logging.getLogger("ha_sentinel.agent")

_PROBE_MAP: dict[ProbeType, type[BaseProbe]] = {
    ProbeType.HTTP: HTTPProbe,
    ProbeType.TCP: TCPProbe,
    ProbeType.DNS: DNSProbe,
    ProbeType.SSL: SSLProbe,
    ProbeType.ICMP: ICMPProbe,
    ProbeType.DOCKER: DockerProbe,
    ProbeType.PROCESS: ProcessProbe,
    ProbeType.CUSTOM: CustomProbe,
}

_NOTIFIER_MAP: dict[str, type] = {
    "slack": SlackNotifier,
    "email": EmailNotifier,
    "pagerduty": PagerDutyNotifier,
    "webhook": WebhookNotifier,
    "discord": DiscordNotifier,
}


class SentinelAgent:
    """Production-ready autonomous monitoring agent."""

    def __init__(self, config: AgentConfig | None = None, config_path: str | None = None) -> None:
        self._config = config or load_config(config_path)
        setup_logging(self._config.log_level, self._config.data_dir)

        logger.info(
            "Initializing %s v%s with %d targets",
            __agent_name__, __version__, len(self._config.targets),
        )

        self.db = Database(self._config.data_dir)
        self.metrics = MetricsCollector(self.db)

        self._notification_dispatcher = NotificationDispatcher(
            cooldown_seconds=self._config.notification_cooldown_seconds
        )
        self._setup_notifications()

        self.incident_manager = IncidentManager(
            db=self.db,
            on_incident=self._on_incident,
            escalation_after_minutes=self._config.escalation_after_minutes,
        )

        self._remediation = RemediationEngine(
            enabled=self._config.remediation_enabled,
            max_per_hour=self._config.max_remediation_per_hour,
        )

        self._probes: dict[ProbeType, BaseProbe] = {}
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._api_server = None

    @property
    def targets(self) -> list[MonitorTarget]:
        return [t for t in self._config.targets if t.enabled]

    def get_target(self, target_id: str) -> MonitorTarget | None:
        for t in self._config.targets:
            if t.id == target_id:
                return t
        return None

    def _setup_notifications(self) -> None:
        for ch in self._config.notification_channels:
            if not ch.enabled:
                continue
            notifier_cls = _NOTIFIER_MAP.get(ch.channel_type)
            if notifier_cls:
                self._notification_dispatcher.register(ch.name, notifier_cls(ch.config))
            else:
                logger.warning("Unknown notification channel type: %s", ch.channel_type)

    def _get_probe(self, probe_type: ProbeType) -> BaseProbe:
        if probe_type not in self._probes:
            cls = _PROBE_MAP.get(probe_type)
            if cls is None:
                raise ValueError(f"No probe registered for type: {probe_type}")
            self._probes[probe_type] = cls()
        return self._probes[probe_type]

    async def _on_incident(self, incident: Incident, event_type: str) -> None:
        target = self.get_target(incident.target_id)
        channels = target.notification_channels if target and target.notification_channels else None

        await self._notification_dispatcher.dispatch(incident, event_type, channels)

        if (
            event_type in ("opened", "escalated", "fatal_escalation")
            and target
            and target.remediation_enabled
        ):
            await self._remediation.attempt_remediation(target, incident)
            self.db.save_incident(incident)

    async def _check_target(self, target: MonitorTarget) -> None:
        probe = self._get_probe(target.probe_type)
        result = await probe.execute_with_retries(target)

        self.metrics.record(result)
        await self.incident_manager.process_result(target, result)

        level = logging.DEBUG if result.is_healthy else logging.WARNING
        logger.log(
            level,
            "[%s] %s — %s (%0.fms)",
            target.id, result.status.value, result.message, result.response_time_ms,
        )

    async def _target_loop(self, target: MonitorTarget) -> None:
        jitter = random.uniform(0, self._config.check_jitter_seconds)
        await asyncio.sleep(jitter)

        while self._running:
            try:
                await self._check_target(target)
            except Exception as exc:
                logger.error("Unhandled error checking %s: %s", target.id, exc, exc_info=True)
            await asyncio.sleep(target.interval_seconds)

    async def _heartbeat_loop(self) -> None:
        if not self._config.heartbeat_url:
            return

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self._config.heartbeat_url,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status < 300:
                            logger.debug("Heartbeat sent successfully")
            except Exception as exc:
                logger.warning("Heartbeat failed: %s", exc)

            await asyncio.sleep(self._config.heartbeat_interval_seconds)

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(3600)
            try:
                self.db.cleanup_old_data(
                    self._config.metrics_retention_days,
                    self._config.incident_retention_days,
                )
                self.metrics.flush_all()
            except Exception as exc:
                logger.error("Cleanup failed: %s", exc)

    async def run(self) -> None:
        self._running = True
        logger.info(
            "Starting %s v%s — monitoring %d targets",
            __agent_name__, __version__, len(self.targets),
        )

        if self._config.api_enabled:
            from ha_agent.api.server import APIServer
            self._api_server = APIServer(
                agent=self,
                host=self._config.api_host,
                port=self._config.api_port,
                secret=self._config.api_secret,
            )
            await self._api_server.start()

        for target in self.targets:
            task = asyncio.create_task(
                self._target_loop(target), name=f"monitor:{target.id}"
            )
            self._tasks.append(task)
            logger.info(
                "  -> Monitoring %s (%s) every %ds",
                target.name, target.probe_type.value, target.interval_seconds,
            )

        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="heartbeat"))
        self._tasks.append(asyncio.create_task(self._cleanup_loop(), name="cleanup"))

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Agent tasks cancelled")

    async def stop(self) -> None:
        logger.info("Stopping %s...", __agent_name__)
        self._running = False

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._api_server:
            await self._api_server.stop()

        for probe in self._probes.values():
            if hasattr(probe, "close"):
                await probe.close()

        self.metrics.flush_all()
        logger.info("%s stopped cleanly.", __agent_name__)


def run_agent(config_path: str | None = None) -> None:
    """Entry point for running the agent from CLI."""
    agent = SentinelAgent(config_path=config_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal() -> None:
        loop.create_task(agent.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(agent.run())
    except KeyboardInterrupt:
        loop.run_until_complete(agent.stop())
    finally:
        loop.close()
