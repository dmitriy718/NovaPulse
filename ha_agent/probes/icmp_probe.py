"""ICMP ping monitoring probe."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.icmp")

_RTT_REGEX = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)
_LOSS_REGEX = re.compile(r"(\d+)%\s*(?:packet\s*)?loss", re.IGNORECASE)


class ICMPProbe(BaseProbe):
    probe_type = ProbeType.ICMP

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        host = target.endpoint.replace("icmp://", "").replace("ping://", "").strip("/")
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "3", "-W", str(target.timeout_seconds), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=target.timeout_seconds + 5
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            output = stdout.decode("utf-8", errors="replace")

            loss_match = _LOSS_REGEX.search(output)
            loss_pct = int(loss_match.group(1)) if loss_match else 100

            rtt_matches = _RTT_REGEX.findall(output)
            avg_rtt = (
                sum(float(r) for r in rtt_matches) / len(rtt_matches)
                if rtt_matches
                else 0
            )

            if loss_pct == 100:
                status = TargetStatus.DOWN
                msg = f"ICMP {host}: 100% packet loss"
            elif loss_pct > 0:
                status = TargetStatus.DEGRADED
                msg = f"ICMP {host}: {loss_pct}% loss, avg RTT {avg_rtt:.1f}ms"
            elif avg_rtt > target.response_time_crit_ms:
                status = TargetStatus.DEGRADED
                msg = f"ICMP {host}: high latency {avg_rtt:.1f}ms"
            else:
                status = TargetStatus.UP
                msg = f"ICMP {host}: {avg_rtt:.1f}ms, 0% loss"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.ICMP,
                status=status,
                response_time_ms=avg_rtt or elapsed_ms,
                message=msg,
                metadata={
                    "host": host,
                    "packet_loss_pct": loss_pct,
                    "avg_rtt_ms": avg_rtt,
                },
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.ICMP,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"ICMP ping failed for {host}: {exc}",
            )
