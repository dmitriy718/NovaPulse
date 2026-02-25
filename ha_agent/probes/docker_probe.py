"""Docker container health monitoring probe."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.docker")


class DockerProbe(BaseProbe):
    probe_type = ProbeType.DOCKER

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        container_name = target.endpoint.replace("docker://", "").strip("/")
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format",
                '{"State":{{json .State}},"Name":{{json .Name}}}',
                container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=target.timeout_seconds
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            if proc.returncode != 0:
                return ProbeResult(
                    target_id=target.id,
                    probe_type=ProbeType.DOCKER,
                    status=TargetStatus.DOWN,
                    response_time_ms=elapsed_ms,
                    message=f"Container '{container_name}' not found or docker unavailable",
                )

            info = json.loads(stdout.decode())
            state = info.get("State", {})
            running = state.get("Running", False)
            health_status = state.get("Health", {}).get("Status", "none")
            restart_count = state.get("RestartCount", 0)

            if not running:
                status = TargetStatus.DOWN
                msg = f"Container '{container_name}' not running (status: {state.get('Status', 'unknown')})"
            elif health_status == "unhealthy":
                status = TargetStatus.DOWN
                msg = f"Container '{container_name}' unhealthy"
            elif health_status == "starting":
                status = TargetStatus.DEGRADED
                msg = f"Container '{container_name}' starting up"
            else:
                status = TargetStatus.UP
                msg = f"Container '{container_name}' running"
                if health_status == "healthy":
                    msg += " (healthy)"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DOCKER,
                status=status,
                response_time_ms=elapsed_ms,
                message=msg,
                metadata={
                    "container": container_name,
                    "running": running,
                    "health": health_status,
                    "restart_count": restart_count,
                    "pid": state.get("Pid", 0),
                },
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.DOCKER,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"Docker probe failed for '{container_name}': {exc}",
            )
