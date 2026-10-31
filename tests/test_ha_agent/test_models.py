"""Tests for HA-SentinelAI data models."""

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
    UptimeRecord,
)


class TestProbeResult:
    def test_healthy_statuses(self):
        for status in (TargetStatus.UP, TargetStatus.MAINTENANCE):
            result = ProbeResult(
                target_id="t1",
                probe_type=ProbeType.HTTP,
                status=status,
                response_time_ms=50,
            )
            assert result.is_healthy is True

    def test_unhealthy_statuses(self):
        for status in (TargetStatus.DOWN, TargetStatus.DEGRADED, TargetStatus.UNKNOWN):
            result = ProbeResult(
                target_id="t1",
                probe_type=ProbeType.HTTP,
                status=status,
                response_time_ms=50,
            )
            assert result.is_healthy is False

    def test_auto_generated_fields(self):
        result = ProbeResult(
            target_id="t1",
            probe_type=ProbeType.TCP,
            status=TargetStatus.UP,
            response_time_ms=10,
        )
        assert result.check_id  # non-empty
        assert result.timestamp > 0
        assert result.metadata == {}


class TestIncident:
    def test_resolve(self):
        inc = Incident(target_id="t1", title="test")
        assert inc.state == IncidentState.OPEN
        inc.resolve(auto=True)
        assert inc.state == IncidentState.AUTO_RESOLVED
        assert inc.resolved_at is not None

    def test_acknowledge(self):
        inc = Incident(target_id="t1", title="test")
        inc.acknowledge(by="admin")
        assert inc.state == IncidentState.ACKNOWLEDGED
        assert inc.acknowledged_by == "admin"
        assert inc.acknowledged_at is not None

    def test_duration(self):
        start = time.time() - 100
        inc = Incident(target_id="t1", title="test", started_at=start)
        assert inc.duration_seconds >= 99

    def test_duration_when_resolved(self):
        start = time.time() - 200
        inc = Incident(target_id="t1", title="test", started_at=start)
        inc.resolve()
        assert 199 <= inc.duration_seconds <= 201


class TestUptimeRecord:
    def test_uptime_pct_all_successful(self):
        rec = UptimeRecord(
            target_id="t1",
            period_start=0,
            period_end=300,
            total_checks=100,
            successful_checks=100,
        )
        assert rec.uptime_pct == 100.0

    def test_uptime_pct_partial(self):
        rec = UptimeRecord(
            target_id="t1",
            period_start=0,
            period_end=300,
            total_checks=100,
            successful_checks=95,
        )
        assert rec.uptime_pct == 95.0

    def test_uptime_pct_zero_checks(self):
        rec = UptimeRecord(
            target_id="t1",
            period_start=0,
            period_end=300,
            total_checks=0,
            successful_checks=0,
        )
        assert rec.uptime_pct == 100.0


class TestMonitorTarget:
    def test_defaults(self):
        t = MonitorTarget(
            id="test",
            name="Test",
            probe_type=ProbeType.HTTP,
            endpoint="https://example.com",
        )
        assert t.interval_seconds == 30
        assert t.timeout_seconds == 10
        assert t.retries == 2
        assert t.method == "GET"
        assert t.enabled is True
        assert t.remediation_enabled is False
