"""Base notifier and multi-channel dispatcher."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from ha_agent.config import NotificationChannelConfig
from ha_agent.models import Incident

logger = logging.getLogger("ha_sentinel.notifications")


class BaseNotifier(ABC):
    """Abstract base for all notification channels."""

    channel_type: str = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._enabled = True

    @abstractmethod
    async def send(self, incident: Incident, event_type: str) -> bool:
        """Send notification. Returns True on success."""

    @abstractmethod
    async def send_recovery(self, incident: Incident) -> bool:
        """Send recovery notification. Returns True on success."""

    def _format_title(self, incident: Incident, event_type: str) -> str:
        emoji_map = {
            "opened": "\u26a0\ufe0f",
            "escalated": "\U0001f534",
            "fatal_escalation": "\U0001f6a8",
            "resolved": "\u2705",
        }
        emoji = emoji_map.get(event_type, "\u2139\ufe0f")
        return f"{emoji} [{incident.severity.value.upper()}] {incident.title}"

    def _format_body(self, incident: Incident, event_type: str) -> str:
        duration = f"{incident.duration_seconds:.0f}s"
        lines = [
            f"Target: {incident.target_name} ({incident.target_id})",
            f"Status: {incident.state.value}",
            f"Severity: {incident.severity.value}",
            f"Duration: {duration}",
            f"Description: {incident.description}",
        ]
        if incident.remediation_attempts:
            last = incident.remediation_attempts[-1]
            lines.append(
                f"Last remediation: {last.get('type', 'unknown')} — "
                f"{'success' if last.get('success') else 'failed'}"
            )
        return "\n".join(lines)


class NotificationDispatcher:
    """Routes notifications to the appropriate channels with cooldown tracking."""

    def __init__(self, cooldown_seconds: int = 300) -> None:
        self._notifiers: dict[str, BaseNotifier] = {}
        self._cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}

    def register(self, name: str, notifier: BaseNotifier) -> None:
        self._notifiers[name] = notifier
        logger.info("Registered notification channel: %s (%s)", name, notifier.channel_type)

    async def dispatch(
        self,
        incident: Incident,
        event_type: str,
        channels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        targets = channels or list(self._notifiers.keys())

        for name in targets:
            notifier = self._notifiers.get(name)
            if notifier is None:
                continue

            cooldown_key = f"{name}:{incident.target_id}:{event_type}"
            last = self._last_sent.get(cooldown_key, 0)
            if event_type not in ("resolved", "fatal_escalation"):
                if time.time() - last < self._cooldown_seconds:
                    continue

            try:
                if event_type == "resolved":
                    success = await notifier.send_recovery(incident)
                else:
                    success = await notifier.send(incident, event_type)

                self._last_sent[cooldown_key] = time.time()
                result = {
                    "channel": name,
                    "type": notifier.channel_type,
                    "event": event_type,
                    "success": success,
                    "timestamp": time.time(),
                }
                results.append(result)
                incident.notification_log.append(result)
            except Exception as exc:
                logger.error("Notification to %s failed: %s", name, exc)
                results.append({
                    "channel": name,
                    "type": notifier.channel_type,
                    "event": event_type,
                    "success": False,
                    "error": str(exc),
                    "timestamp": time.time(),
                })

        return results
