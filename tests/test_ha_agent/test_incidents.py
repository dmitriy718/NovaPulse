"""Tests for HA-SentinelAI incident management."""

import asyncio
import time
import pytest

from ha_agent.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
    MonitorTarget,
    ProbeResult,
    ProbeType,
    TargetStatus,
)
from ha_agent.incidents.manager import IncidentManager
from ha_agent.storage.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test_data"))


def _make_target(**kw) -> MonitorTarget:
    defaults = {
        "id": "test_target",
        "name": "Test Target",
        "probe_type": ProbeType.HTTP,
        "endpoint": "https://example.com",
        "consecutive_failures_warn": 2,
        "consecutive_failures_crit": 3,
    }
    defaults.update(kw)
    return MonitorTarget(**defaults)


def _make_result(status: TargetStatus = TargetStatus.DOWN, **kw) -> ProbeResult:
    defaults = {
        "target_id": "test_target",
        "probe_type": ProbeType.HTTP,
        "status": status,
        "response_time_ms": 100.0,
        "message": f"Status: {status.value}",
    }
    defaults.update(kw)
    return ProbeResult(**defaults)


class TestIncidentManager:
    @pytest.mark.asyncio
    async def test_no_incident_on_single_failure(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        result = _make_result(TargetStatus.DOWN)
        incident = await mgr.process_result(target, result)
        assert incident is None
        assert len(mgr.get_active_incidents()) == 0

    @pytest.mark.asyncio
    async def test_incident_opens_after_threshold(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        for _ in range(2):
            incident = await mgr.process_result(target, _make_result(TargetStatus.DOWN))

        assert incident is not None
        assert incident.state == IncidentState.OPEN
        assert incident.severity == IncidentSeverity.WARNING
        assert len(mgr.get_active_incidents()) == 1

    @pytest.mark.asyncio
    async def test_incident_escalates_to_critical(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        for _ in range(3):
            incident = await mgr.process_result(target, _make_result(TargetStatus.DOWN))

        assert incident is not None
        assert incident.severity == IncidentSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_incident_auto_resolves(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        for _ in range(3):
            await mgr.process_result(target, _make_result(TargetStatus.DOWN))
        assert len(mgr.get_active_incidents()) == 1

        for _ in range(2):
            incident = await mgr.process_result(target, _make_result(TargetStatus.UP))

        assert len(mgr.get_active_incidents()) == 0
        assert incident is not None
        assert incident.state == IncidentState.AUTO_RESOLVED

    @pytest.mark.asyncio
    async def test_acknowledge_incident(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        for _ in range(2):
            incident = await mgr.process_result(target, _make_result(TargetStatus.DOWN))

        assert incident is not None
        success = mgr.acknowledge_incident(incident.id, by="admin")
        assert success is True
        assert mgr.get_active_incidents()[0].state == IncidentState.ACKNOWLEDGED

    @pytest.mark.asyncio
    async def test_manual_resolve(self, db):
        mgr = IncidentManager(db=db)
        target = _make_target()

        for _ in range(2):
            incident = await mgr.process_result(target, _make_result(TargetStatus.DOWN))

        assert incident is not None
        success = mgr.resolve_incident(incident.id)
        assert success is True
        assert len(mgr.get_active_incidents()) == 0

    @pytest.mark.asyncio
    async def test_notification_callback_fires(self, db):
        events = []

        async def on_incident(inc, event_type):
            events.append((inc.id, event_type))

        mgr = IncidentManager(db=db, on_incident=on_incident)
        target = _make_target()

        for _ in range(3):
            await mgr.process_result(target, _make_result(TargetStatus.DOWN))

        assert any(e[1] == "opened" for e in events)

        for _ in range(2):
            await mgr.process_result(target, _make_result(TargetStatus.UP))

        assert any(e[1] == "resolved" for e in events)
