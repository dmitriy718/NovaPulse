"""Abstract base class for all monitoring probes."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

from ha_agent.models import MonitorTarget, ProbeResult, ProbeType, TargetStatus

logger = logging.getLogger("ha_sentinel.probes")


class BaseProbe(ABC):
    probe_type: ProbeType

    @abstractmethod
    async def execute(self, target: MonitorTarget) -> ProbeResult:
        """Run probe against target, return a ProbeResult."""

    async def execute_with_retries(self, target: MonitorTarget) -> ProbeResult:
        last_result: ProbeResult | None = None
        for attempt in range(1, target.retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.execute(target),
                    timeout=target.timeout_seconds,
                )
                if result.is_healthy:
                    return result
                last_result = result
            except asyncio.TimeoutError:
                last_result = ProbeResult(
                    target_id=target.id,
                    probe_type=self.probe_type,
                    status=TargetStatus.DOWN,
                    response_time_ms=target.timeout_seconds * 1000,
                    message=f"Timeout after {target.timeout_seconds}s (attempt {attempt}/{target.retries})",
                )
            except Exception as exc:
                last_result = ProbeResult(
                    target_id=target.id,
                    probe_type=self.probe_type,
                    status=TargetStatus.DOWN,
                    response_time_ms=0,
                    message=f"Probe error: {exc} (attempt {attempt}/{target.retries})",
                )
            if attempt < target.retries:
                await asyncio.sleep(min(2 ** attempt, 10))

        return last_result or ProbeResult(
            target_id=target.id,
            probe_type=self.probe_type,
            status=TargetStatus.UNKNOWN,
            response_time_ms=0,
            message="No probe result produced",
        )
