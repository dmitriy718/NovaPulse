"""Slack notification channel."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from ha_agent.models import Incident, IncidentSeverity
from ha_agent.notifications.base import BaseNotifier

logger = logging.getLogger("ha_sentinel.notifications.slack")


class SlackNotifier(BaseNotifier):
    channel_type = "slack"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._webhook_url = config.get("webhook_url", "")
        self._channel = config.get("channel", "")
        self._username = config.get("username", "HA-SentinelAI")

    async def send(self, incident: Incident, event_type: str) -> bool:
        color_map = {
            IncidentSeverity.INFO: "#36a64f",
            IncidentSeverity.WARNING: "#daa038",
            IncidentSeverity.CRITICAL: "#cc0000",
            IncidentSeverity.FATAL: "#8b0000",
        }
        payload = {
            "username": self._username,
            "attachments": [
                {
                    "color": color_map.get(incident.severity, "#cc0000"),
                    "title": self._format_title(incident, event_type),
                    "text": self._format_body(incident, event_type),
                    "fields": [
                        {"title": "Target", "value": incident.target_name, "short": True},
                        {"title": "Severity", "value": incident.severity.value, "short": True},
                        {"title": "Duration", "value": f"{incident.duration_seconds:.0f}s", "short": True},
                        {"title": "Event", "value": event_type, "short": True},
                    ],
                    "footer": "HA-SentinelAI",
                    "ts": int(incident.started_at),
                }
            ],
        }
        if self._channel:
            payload["channel"] = self._channel

        return await self._post(payload)

    async def send_recovery(self, incident: Incident) -> bool:
        payload = {
            "username": self._username,
            "attachments": [
                {
                    "color": "#36a64f",
                    "title": f"\u2705 RESOLVED: {incident.target_name}",
                    "text": (
                        f"Incident {incident.id} has been resolved.\n"
                        f"Duration: {incident.duration_seconds:.0f}s"
                    ),
                    "footer": "HA-SentinelAI",
                }
            ],
        }
        if self._channel:
            payload["channel"] = self._channel

        return await self._post(payload)

    async def _post(self, payload: dict) -> bool:
        if not self._webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.error("Slack notification failed: %s", exc)
            return False
