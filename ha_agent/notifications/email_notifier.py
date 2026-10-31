"""Email (SMTP) notification channel."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from ha_agent.models import Incident
from ha_agent.notifications.base import BaseNotifier

logger = logging.getLogger("ha_sentinel.notifications.email")


class EmailNotifier(BaseNotifier):
    channel_type = "email"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._smtp_host = config.get("smtp_host", "localhost")
        self._smtp_port = int(config.get("smtp_port", 587))
        self._use_tls = config.get("use_tls", True)
        self._username = config.get("username", "")
        self._password = config.get("password", "")
        self._from_addr = config.get("from", "ha-sentinel@localhost")
        self._to_addrs = config.get("to", [])
        if isinstance(self._to_addrs, str):
            self._to_addrs = [self._to_addrs]

    async def send(self, incident: Incident, event_type: str) -> bool:
        subject = self._format_title(incident, event_type)
        body = self._format_body(incident, event_type)
        html = self._build_html(incident, event_type)
        return await self._send_email(subject, body, html)

    async def send_recovery(self, incident: Incident) -> bool:
        subject = f"RESOLVED: {incident.target_name} — incident {incident.id}"
        body = (
            f"Incident for {incident.target_name} has been resolved.\n"
            f"Duration: {incident.duration_seconds:.0f}s\n"
            f"Incident ID: {incident.id}"
        )
        html = self._build_html(incident, "resolved")
        return await self._send_email(subject, body, html)

    def _build_html(self, incident: Incident, event_type: str) -> str:
        color = {
            "opened": "#daa038",
            "escalated": "#cc0000",
            "fatal_escalation": "#8b0000",
            "resolved": "#36a64f",
        }.get(event_type, "#666")

        return f"""
        <html><body style="font-family: Arial, sans-serif;">
        <div style="border-left: 4px solid {color}; padding: 12px; margin: 10px 0;">
            <h2 style="color: {color}; margin: 0 0 8px 0;">{self._format_title(incident, event_type)}</h2>
            <table style="border-collapse: collapse;">
                <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Target</td><td>{incident.target_name}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Severity</td><td>{incident.severity.value}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">State</td><td>{incident.state.value}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Duration</td><td>{incident.duration_seconds:.0f}s</td></tr>
                <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Description</td><td>{incident.description}</td></tr>
            </table>
        </div>
        <p style="color: #999; font-size: 12px;">Sent by HA-SentinelAI</p>
        </body></html>
        """

    async def _send_email(self, subject: str, body: str, html: str) -> bool:
        if not self._to_addrs:
            logger.warning("No email recipients configured")
            return False

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, self._send_sync, subject, body, html
            )
            return True
        except Exception as exc:
            logger.error("Email notification failed: %s", exc)
            return False

    def _send_sync(self, subject: str, body: str, html: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)

        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))

        if self._use_tls:
            server = smtplib.SMTP(self._smtp_host, self._smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(self._smtp_host, self._smtp_port)

        if self._username:
            server.login(self._username, self._password)

        server.sendmail(self._from_addr, self._to_addrs, msg.as_string())
        server.quit()
