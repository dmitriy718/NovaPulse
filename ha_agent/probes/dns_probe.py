"""DNS resolution monitoring probe."""

from __future__ import annotations

import asyncio
import logging
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.dns")


class DNSProbe(BaseProbe):
    probe_type = ProbeType.DNS

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        hostname = target.endpoint.replace("dns://", "").strip("/")
        start = time.monotonic()

        try:
            import dns.asyncresolver

            resolver = dns.asyncresolver.Resolver()
            if target.dns_server:
                resolver.nameservers = [target.dns_server]
            resolver.lifetime = target.timeout_seconds

            answers = await resolver.resolve(hostname, target.dns_record_type)
            elapsed_ms = (time.monotonic() - start) * 1000

            resolved = sorted(str(r) for r in answers)

            if target.dns_expected_values:
                expected = sorted(target.dns_expected_values)
                if resolved == expected:
                    status = TargetStatus.UP
                    msg = f"DNS {hostname} {target.dns_record_type} -> {resolved}"
                else:
                    status = TargetStatus.DOWN
                    msg = (
                        f"DNS mismatch for {hostname}: "
                        f"expected {expected}, got {resolved}"
                    )
            else:
                status = TargetStatus.UP if resolved else TargetStatus.DOWN
                msg = f"DNS {hostname} {target.dns_record_type} -> {resolved}"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DNS,
                status=status,
                response_time_ms=elapsed_ms,
                message=msg,
                metadata={
                    "hostname": hostname,
                    "record_type": target.dns_record_type,
                    "resolved": resolved,
                },
            )
        except ImportError:
            return await self._fallback_resolve(target, hostname, start)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DNS,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"DNS resolution failed for {hostname}: {exc}",
            )

    async def _fallback_resolve(
        self, target: MonitorTarget, hostname: str, start: float
    ) -> ProbeResult:
        """Fallback using stdlib getaddrinfo when dnspython is not installed."""
        loop = asyncio.get_event_loop()
        try:
            infos = await loop.getaddrinfo(hostname, None)
            elapsed_ms = (time.monotonic() - start) * 1000
            addrs = sorted({info[4][0] for info in infos})
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DNS,
                status=TargetStatus.UP if addrs else TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"DNS {hostname} -> {addrs} (stdlib fallback)",
                metadata={"hostname": hostname, "resolved": addrs},
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DNS,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"DNS fallback failed for {hostname}: {exc}",
            )
