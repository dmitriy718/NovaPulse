"""Custom script-based monitoring probe."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus
from ha_agent.probes.base import BaseProbe

logger = logging.getLogger("ha_sentinel.probes.custom")


class CustomProbe(BaseProbe):
    probe_type = ProbeType.CUSTOM

    async def execute(self, target: MonitorTarget) -> ProbeResult:
        command = target.endpoint
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=target.timeout_seconds
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            metadata: dict = {"exit_code": proc.returncode, "stdout": stdout_text[:2000]}
            if stderr_text:
                metadata["stderr"] = stderr_text[:1000]

            # Try to parse JSON output for structured results
            try:
                parsed = json.loads(stdout_text)
                if isinstance(parsed, dict):
                    metadata.update(parsed)
            except (json.JSONDecodeError, ValueError):
                pass

            if proc.returncode == 0:
                status = TargetStatus.UP
                msg = f"Custom check passed: {stdout_text[:200]}" if stdout_text else "Custom check passed"
            elif proc.returncode == 1:
                status = TargetStatus.DEGRADED
                msg = f"Custom check warning: {stdout_text[:200]}" if stdout_text else "Custom check returned warning"
            else:
                status = TargetStatus.DOWN
                msg = f"Custom check failed (exit {proc.returncode}): {stderr_text[:200] or stdout_text[:200]}"

            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.CUSTOM,
                status=status,
                response_time_ms=elapsed_ms,
                message=msg,
                metadata=metadata,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                target_id=target.id,
                probe_type=ProbeType.CUSTOM,
                status=TargetStatus.DOWN,
                response_time_ms=elapsed_ms,
                message=f"Custom probe failed: {exc}",
            )
