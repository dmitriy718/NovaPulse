"""HTTP/HTTPS monitoring probe with full response validation."""

from __future__ import annotations

import logging
import re
import time

import aiohttp

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.http")


class HTTPProbe(BaseProbe):
    probe_type = ProbeType.HTTP

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "HA-SentinelAI/1.0"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        session = await self._get_session()
        start = time.monotonic()

        try:
            timeout = aiohttp.ClientTimeout(total=target.timeout_seconds)
            kwargs: dict = {
                "url": target.endpoint,
                "timeout": timeout,
                "headers": target.headers,
                "ssl": True,
                "allow_redirects": True,
            }
            if target.body and target.method in ("POST", "PUT", "PATCH"):
                kwargs["data"] = target.body

            async with session.request(target.method, **kwargs) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                body_text = await resp.text(encoding="utf-8", errors="replace")

                status_ok = resp.status in target.expected_status_codes
                body_match = True
                if target.metadata.get("body_contains"):
                    body_match = target.metadata["body_contains"] in body_text
                if target.metadata.get("body_regex"):
                    body_match = bool(
                        re.search(target.metadata["body_regex"], body_text)
                    )

                if status_ok and body_match:
                    if elapsed_ms > target.response_time_crit_ms:
                        t_status = TargetStatus.DEGRADED
                        msg = f"HTTP {resp.status} OK but slow ({elapsed_ms:.0f}ms)"
                    elif elapsed_ms > target.response_time_warn_ms:
                        t_status = TargetStatus.DEGRADED
                        msg = f"HTTP {resp.status} OK, response slow ({elapsed_ms:.0f}ms)"
                    else:
                        t_status = TargetStatus.UP
                        msg = f"HTTP {resp.status} OK ({elapsed_ms:.0f}ms)"
                else:
                    t_status = TargetStatus.DOWN
                    reasons = []
                    if not status_ok:
                        reasons.append(
                            f"status {resp.status} not in {target.expected_status_codes}"
                        )
                    if not body_match:
                        reasons.append("body content mismatch")
                    msg = f"HTTP check failed: {'; '.join(reasons)}"

                return ProbeResult(
                    target_id=target.id,
                    probe_type=ProbeType.HTTP,
                    status=t_status,
                    response_time_ms=elapsed_ms,
                    message=msg,
                    metadata={
                        "status_code": resp.status,
                        "content_length": len(body_text),
                        "headers": dict(resp.headers),
                    },
                )
        except aiohttp.ClientError as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.HTTP,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"HTTP connection error: {exc}",
            )
