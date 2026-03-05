"""PagerDuty notification channel via Events API v2."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ha_agent.models import Incident, IncidentSeverity
from ha_agent.notifications.base import BaseNotifier

logger = logging.getLogger("ha_sentinel.notifications.pagerduty")

PD_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyNotifier(BaseNotifier):
    channel_type = "pagerduty"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._routing_key = config.get("routing_key", "")

    async def send(self, incident: Incident, event_type: str) -> bool:
        severity_map = {
            IncidentSeverity.INFO: "info",
            IncidentSeverity.WARNING: "warning",
            IncidentSeverity.CRITICAL: "critical",
            IncidentSeverity.FATAL: "critical",
        }
        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": f"ha-sentinel-{incident.target_id}-{incident.id}",
            "payload": {
                "summary": self._format_title(incident, event_type),
                "source": f"ha-sentinel:{incident.target_id}",
                "severity": severity_map.get(incident.severity, "error"),
                "component": incident.target_name,
                "group": incident.target_id,
                "custom_details": {
                    "description": incident.description,
                    "duration_seconds": incident.duration_seconds,
                    "event_type": event_type,
                },
            },
        }
        return await self._post(payload)

    async def send_recovery(self, incident: Incident) -> bool:
        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": f"ha-sentinel-{incident.target_id}-{incident.id}",
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> bool:
        if not self._routing_key:
            logger.warning("PagerDuty routing key not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PD_EVENTS_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status in (200, 202)
        except Exception as exc:
            logger.error("PagerDuty notification failed: %s", exc)
            return False
