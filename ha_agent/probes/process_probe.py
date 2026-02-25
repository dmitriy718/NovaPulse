"""System process monitoring probe."""

from __future__ import annotations

import asyncio
import logging
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.process")


class ProcessProbe(BaseProbe):
    probe_type = ProbeType.PROCESS

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        process_name = target.endpoint.replace("process://", "").strip("/")
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-f", process_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=target.timeout_seconds
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            pids = [p.strip() for p in stdout.decode().strip().split("\n") if p.strip()]

            if pids:
                cpu, mem = await _get_process_stats(pids[0])
                status = TargetStatus.UP
                msg = f"Process '{process_name}' running (PIDs: {', '.join(pids[:5])})"
                return ProbeResult(
                    target_id=target.id,
                    probe_type=ProbeType.PROCESS,
                    status=status,
                    response_time_ms=elapsed_ms,
                    message=msg,
                    metadata={
                        "process": process_name,
                        "pid_count": len(pids),
                        "pids": pids[:10],
                        "cpu_pct": cpu,
                        "mem_pct": mem,
                    },
                )
            else:
                return ProbeResult(
                    target_id=target.id,
                    probe_type=ProbeType.PROCESS,
                    status=TargetStatus.DOWN,
                    response_time_ms=elapsed_ms,
                    message=f"Process '{process_name}' not found",
                )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.PROCESS,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"Process probe failed for '{process_name}': {exc}",
            )


async def _get_process_stats(pid: str) -> tuple[float, float]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ps", "-p", pid, "-o", "%cpu,%mem", "--no-headers",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        parts = stdout.decode().strip().split()
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
    except Exception:
        pass
    return 0.0, 0.0
