"""TCP port monitoring probe."""

from __future__ import annotations

import asyncio
import logging
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.tcp")


class TCPProbe(BaseProbe):
    probe_type = ProbeType.TCP

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        host, port = _parse_host_port(target.endpoint)
        start = time.monotonic()

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=target.timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            writer.close()
            await writer.wait_closed()

            if elapsed_ms > target.response_time_crit_ms:
                status = TargetStatus.DEGRADED
                msg = f"TCP {host}:{port} open but slow ({elapsed_ms:.0f}ms)"
            else:
                status = TargetStatus.UP
                msg = f"TCP {host}:{port} open ({elapsed_ms:.0f}ms)"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.TCP,
                status=status,
                response_time_ms=elapsed_ms,
                message=msg,
                metadata={"host": host, "port": port},
            )
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError) as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.TCP,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"TCP {host}:{port} unreachable: {exc}",
                metadata={"host": host, "port": port},
            )


def _parse_host_port(endpoint: str) -> tuple[str, int]:
    endpoint = endpoint.replace("tcp://", "").replace("//", "")
    if ":" in endpoint:
        parts = endpoint.rsplit(":", 1)
        return parts[0], int(parts[1])
    return endpoint, 80
