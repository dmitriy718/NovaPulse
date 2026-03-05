"""Discord notification channel via webhooks."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ha_agent.models import Incident, IncidentSeverity
from ha_agent.notifications.base import BaseNotifier

logger = logging.getLogger("ha_sentinel.notifications.discord")


class DiscordNotifier(BaseNotifier):
    channel_type = "discord"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._webhook_url = config.get("webhook_url", "")
        self._username = config.get("username", "HA-SentinelAI")

    async def send(self, incident: Incident, event_type: str) -> bool:
        color_map = {
            IncidentSeverity.INFO: 3066993,
            IncidentSeverity.WARNING: 15105570,
            IncidentSeverity.CRITICAL: 15158332,
            IncidentSeverity.FATAL: 10038562,
        }
        embed = {
            "title": self._format_title(incident, event_type),
            "description": self._format_body(incident, event_type),
            "color": color_map.get(incident.severity, 15158332),
            "fields": [
                {"name": "Target", "value": incident.target_name, "inline": True},
                {"name": "Severity", "value": incident.severity.value, "inline": True},
                {"name": "Duration", "value": f"{incident.duration_seconds:.0f}s", "inline": True},
            ],
            "footer": {"text": "HA-SentinelAI"},
        }
        payload = {
            "username": self._username,
            "embeds": [embed],
        }
        return await self._post(payload)

    async def send_recovery(self, incident: Incident) -> bool:
        embed = {
            "title": f"\u2705 RESOLVED: {incident.target_name}",
            "description": (
                f"Incident {incident.id} resolved after "
                f"{incident.duration_seconds:.0f}s"
            ),
            "color": 3066993,
            "footer": {"text": "HA-SentinelAI"},
        }
        payload = {
            "username": self._username,
            "embeds": [embed],
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> bool:
        if not self._webhook_url:
            logger.warning("Discord webhook URL not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status in (200, 204)
        except Exception as exc:
            logger.error("Discord notification failed: %s", exc)
            return False
