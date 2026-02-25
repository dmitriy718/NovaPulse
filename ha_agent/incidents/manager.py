"""Incident lifecycle manager — open, escalate, resolve incidents automatically."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Coroutine

from ha_agent.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
    MonitorTarget,
    ProbeResult,
    TargetStatus,
)
from ha_agent.storage.database import Database

logger = logging.getLogger("ha_sentinel.incidents")

OnIncidentCallback = Callable[[Incident, str], Coroutine[Any, Any, None]]


class IncidentManager:
    def __init__(
        self,
        db: Database,
        on_incident: OnIncidentCallback | None = None,
        escalation_after_minutes: int = 15,
    ) -> None:
        self._db = db
        self._on_incident = on_incident
        self._escalation_minutes = escalation_after_minutes
        self._active_incidents: dict[str, Incident] = {}
        self._load_active()

    def _load_active(self) -> None:
        for inc in self._db.get_open_incidents():
            self._active_incidents[inc.target_id] = inc

    async def process_result(
        self, target: MonitorTarget, result: ProbeResult
    ) -> Incident | None:
        state = self._db.get_target_state(target.id)
        prev_failures = state.get("consecutive_failures", 0)
        prev_successes = state.get("consecutive_successes", 0)

        if result.is_healthy:
            new_failures = 0
            new_successes = prev_successes + 1
        else:
            new_failures = prev_failures + 1
            new_successes = 0

        self._db.update_target_state(
            target_id=target.id,
            status=result.status.value,
            response_ms=result.response_time_ms,
            consecutive_failures=new_failures,
            consecutive_successes=new_successes,
        )

        incident = None

        if result.is_healthy:
            incident = await self._try_resolve(target, result, new_successes)
        else:
            incident = await self._try_open_or_escalate(
                target, result, new_failures
            )

        return incident

    async def _try_open_or_escalate(
        self, target: MonitorTarget, result: ProbeResult, failures: int
    ) -> Incident | None:
        existing = self._active_incidents.get(target.id)

        if existing is None and failures >= target.consecutive_failures_warn:
            severity = (
                IncidentSeverity.CRITICAL
                if failures >= target.consecutive_failures_crit
                else IncidentSeverity.WARNING
            )
            incident = Incident(
                target_id=target.id,
                target_name=target.name,
                severity=severity,
                state=IncidentState.OPEN,
                title=f"{target.name} is {result.status.value}",
                description=result.message,
                probe_results=[result],
            )
            self._active_incidents[target.id] = incident
            self._db.save_incident(incident)
            logger.warning(
                "INCIDENT OPENED: %s [%s] — %s",
                incident.id, severity.value, incident.title,
            )
            if self._on_incident:
                await self._on_incident(incident, "opened")
            return incident

        if existing is not None:
            existing.probe_results.append(result)

            if (
                failures >= target.consecutive_failures_crit
                and existing.severity == IncidentSeverity.WARNING
            ):
                existing.severity = IncidentSeverity.CRITICAL
                existing.title = f"{target.name} is {result.status.value} (escalated)"
                self._db.save_incident(existing)
                logger.warning(
                    "INCIDENT ESCALATED: %s -> CRITICAL", existing.id
                )
                if self._on_incident:
                    await self._on_incident(existing, "escalated")

            elapsed = time.time() - existing.started_at
            if (
                elapsed > self._escalation_minutes * 60
                and existing.severity != IncidentSeverity.FATAL
                and existing.state == IncidentState.OPEN
            ):
                existing.severity = IncidentSeverity.FATAL
                existing.title = f"{target.name} — prolonged outage (FATAL)"
                self._db.save_incident(existing)
                logger.critical(
                    "INCIDENT FATAL ESCALATION: %s (open %d min)",
                    existing.id, int(elapsed / 60),
                )
                if self._on_incident:
                    await self._on_incident(existing, "fatal_escalation")

            return existing

        return None

    async def _try_resolve(
        self, target: MonitorTarget, result: ProbeResult, successes: int
    ) -> Incident | None:
        existing = self._active_incidents.get(target.id)
        if existing is None:
            return None

        resolve_threshold = max(2, target.consecutive_failures_warn)
        if successes >= resolve_threshold:
            existing.resolve(auto=True)
            self._db.save_incident(existing)
            del self._active_incidents[target.id]
            logger.info(
                "INCIDENT RESOLVED: %s — %s (duration: %.0fs)",
                existing.id, target.name, existing.duration_seconds,
            )
            if self._on_incident:
                await self._on_incident(existing, "resolved")
            return existing

        return None

    def get_active_incidents(self) -> list[Incident]:
        return list(self._active_incidents.values())

    def acknowledge_incident(self, incident_id: str, by: str = "api") -> bool:
        for inc in self._active_incidents.values():
            if inc.id == incident_id:
                inc.acknowledge(by=by)
                self._db.save_incident(inc)
                return True
        return False

    def resolve_incident(self, incident_id: str) -> bool:
        for target_id, inc in list(self._active_incidents.items()):
            if inc.id == incident_id:
                inc.resolve(auto=False)
                self._db.save_incident(inc)
                del self._active_incidents[target_id]
                return True
        return False
