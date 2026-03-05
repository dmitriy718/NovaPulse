"""Generic webhook notification channel."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from ha_agent.models import Incident
from ha_agent.notifications.base import BaseNotifier

logger = logging.getLogger("ha_sentinel.notifications.webhook")


class WebhookNotifier(BaseNotifier):
    channel_type = "webhook"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._url = config.get("url", "")
        self._method = config.get("method", "POST")
        self._headers = config.get("headers", {"Content-Type": "application/json"})
        self._secret = config.get("secret", "")

    async def send(self, incident: Incident, event_type: str) -> bool:
        return await self._fire(incident, event_type)

    async def send_recovery(self, incident: Incident) -> bool:
        return await self._fire(incident, "resolved")

    async def _fire(self, incident: Incident, event_type: str) -> bool:
        if not self._url:
            logger.warning("Webhook URL not configured")
            return False

        payload = {
            "event_type": event_type,
            "incident_id": incident.id,
            "target_id": incident.target_id,
            "target_name": incident.target_name,
            "severity": incident.severity.value,
            "state": incident.state.value,
            "title": incident.title,
            "description": incident.description,
            "started_at": incident.started_at,
            "resolved_at": incident.resolved_at,
            "duration_seconds": incident.duration_seconds,
            "source": "ha-sentinel-ai",
        }

        headers = dict(self._headers)
        if self._secret:
            import hashlib
            import hmac
            sig = hmac.new(
                self._secret.encode(), json.dumps(payload).encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Signature-256"] = f"sha256={sig}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    self._method,
                    self._url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    return 200 <= resp.status < 300
        except Exception as exc:
            logger.error("Webhook notification failed: %s", exc)
            return False
