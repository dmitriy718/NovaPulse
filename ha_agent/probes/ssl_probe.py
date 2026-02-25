"""SSL/TLS certificate monitoring probe."""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from datetime import datetime, timezone

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.ssl")


class SSLProbe(BaseProbe):
    probe_type = ProbeType.SSL

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        host, port = _parse_ssl_endpoint(target.endpoint)
        start = time.monotonic()

        loop = asyncio.get_event_loop()
        try:
            cert_info = await asyncio.wait_for(
                loop.run_in_executor(None, _get_cert_info, host, port, target.timeout_seconds),
                timeout=target.timeout_seconds + 2,
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            not_after_str = cert_info.get("notAfter", "")
            not_after = _parse_ssl_date(not_after_str)
            now = datetime.now(timezone.utc)
            days_remaining = (not_after - now).days if not_after else -1

            issuer = _format_cert_field(cert_info.get("issuer", ()))
            subject = _format_cert_field(cert_info.get("subject", ()))

            if days_remaining < 0:
                status = TargetStatus.DOWN
                msg = f"SSL cert for {host} has EXPIRED"
            elif days_remaining <= target.ssl_crit_days:
                status = TargetStatus.DOWN
                msg = f"SSL cert for {host} expires in {days_remaining} days (critical)"
            elif days_remaining <= target.ssl_warn_days:
                status = TargetStatus.DEGRADED
                msg = f"SSL cert for {host} expires in {days_remaining} days (warning)"
            else:
                status = TargetStatus.UP
                msg = f"SSL cert for {host} valid, {days_remaining} days remaining"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.SSL,
                status=status,
                response_time_ms=elapsed_ms,
                message=msg,
                metadata={
                    "host": host,
                    "port": port,
                    "days_remaining": days_remaining,
                    "not_after": not_after_str,
                    "issuer": issuer,
                    "subject": subject,
                },
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.SSL,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"SSL check failed for {host}: {exc}",
            )


def _get_cert_info(host: str, port: int, timeout: int) -> dict:
    import socket

    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            return ssock.getpeercert()  # type: ignore[return-value]


def _parse_ssl_endpoint(endpoint: str) -> tuple[str, int]:
    endpoint = endpoint.replace("https://", "").replace("ssl://", "").strip("/")
    if ":" in endpoint:
        parts = endpoint.rsplit(":", 1)
        return parts[0], int(parts[1])
    return endpoint, 443


def _parse_ssl_date(date_str: str) -> datetime | None:
    formats = [
        "%b %d %H:%M:%S %Y %Z",
        "%b  %d %H:%M:%S %Y %Z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _format_cert_field(field_tuple: tuple) -> str:
    parts = []
    for rdn in field_tuple:
        for attr_type, attr_value in rdn:
            parts.append(f"{attr_type}={attr_value}")
    return ", ".join(parts)
