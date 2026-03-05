"""Tests for HA-SentinelAI storage layer."""

import time
import pytest

from ha_agent.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
    ProbeResult,
    ProbeType,
    TargetStatus,
    UptimeRecord,
)
from ha_agent.storage.database import Database
from ha_agent.storage.metrics import MetricsCollector


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test_data"))


@pytest.fixture
def metrics(db):
    return MetricsCollector(db)


class TestDatabase:
    def test_save_and_get_probe_result(self, db):
        result = ProbeResult(
            target_id="t1",
            probe_type=ProbeType.HTTP,
            status=TargetStatus.UP,
            response_time_ms=42.5,
            message="OK",
        )
        db.save_probe_result(result)
        results = db.get_recent_results("t1", limit=10)
        assert len(results) == 1
        assert results[0]["target_id"] == "t1"
        assert results[0]["response_time_ms"] == 42.5

    def test_target_state_lifecycle(self, db):
        state = db.get_target_state("new_target")
        assert state["current_status"] == "unknown"
        assert state["consecutive_failures"] == 0

        db.update_target_state("new_target", "up", 50.0, 0, 5)
        state = db.get_target_state("new_target")
        assert state["current_status"] == "up"
        assert state["consecutive_successes"] == 5

        db.update_target_state("new_target", "down", 0, 1, 0)
        state = db.get_target_state("new_target")
        assert state["current_status"] == "down"
        assert state["consecutive_failures"] == 1

    def test_save_and_get_incident(self, db):
        inc = Incident(
            target_id="t1",
            target_name="Test",
            severity=IncidentSeverity.CRITICAL,
            state=IncidentState.OPEN,
            title="Server down",
            description="HTTP 500",
        )
        db.save_incident(inc)
        open_incidents = db.get_open_incidents()
        assert len(open_incidents) == 1
        assert open_incidents[0].id == inc.id
        assert open_incidents[0].severity == IncidentSeverity.CRITICAL

    def test_get_open_incidents_by_target(self, db):
        for tid in ("t1", "t2", "t1"):
            inc = Incident(
                target_id=tid,
                target_name=f"Target {tid}",
                severity=IncidentSeverity.WARNING,
                state=IncidentState.OPEN,
                title=f"{tid} down",
            )
            db.save_incident(inc)

        assert len(db.get_open_incidents("t1")) == 2
        assert len(db.get_open_incidents("t2")) == 1

    def test_incident_resolve_persists(self, db):
        inc = Incident(
            target_id="t1",
            severity=IncidentSeverity.WARNING,
            state=IncidentState.OPEN,
            title="test",
        )
        db.save_incident(inc)
        inc.resolve()
        db.save_incident(inc)

        open_list = db.get_open_incidents()
        assert len(open_list) == 0

        all_list = db.get_incidents(limit=10)
        assert len(all_list) == 1
        assert all_list[0].state == IncidentState.RESOLVED

    def test_uptime_records(self, db):
        now = time.time()
        record = UptimeRecord(
            target_id="t1",
            period_start=now - 300,
            period_end=now,
            total_checks=10,
            successful_checks=9,
            avg_response_ms=55.0,
            p95_response_ms=120.0,
            p99_response_ms=200.0,
        )
        db.save_uptime_record(record)
        records = db.get_uptime_records("t1", since=now - 600)
        assert len(records) == 1
        assert records[0]["successful_checks"] == 9

    def test_cleanup_old_data(self, db):
        old_result = ProbeResult(
            target_id="t1",
            probe_type=ProbeType.HTTP,
            status=TargetStatus.UP,
            response_time_ms=10,
            timestamp=time.time() - 200 * 86400,
        )
        db.save_probe_result(old_result)

        new_result = ProbeResult(
            target_id="t1",
            probe_type=ProbeType.HTTP,
            status=TargetStatus.UP,
            response_time_ms=10,
        )
        db.save_probe_result(new_result)

        cleaned = db.cleanup_old_data(metrics_days=90)
        assert cleaned >= 1
        results = db.get_recent_results("t1")
        assert len(results) == 1

    def test_get_all_target_states(self, db):
        db.update_target_state("a", "up", 10, 0, 1)
        db.update_target_state("b", "down", 0, 3, 0)
        states = db.get_all_target_states()
        assert len(states) == 2


class TestMetricsCollector:
    def test_record_and_summary(self, metrics):
        for i in range(5):
            result = ProbeResult(
                target_id="t1",
                probe_type=ProbeType.HTTP,
                status=TargetStatus.UP,
                response_time_ms=50 + i * 10,
                timestamp=time.time() - (4 - i) * 60,
            )
            metrics.record(result)

        metrics.flush_all()
        summary = metrics.get_uptime_summary("t1", hours=1)
        assert summary["total_checks"] == 5
        assert summary["uptime_pct"] == 100.0
        assert summary["avg_response_ms"] > 0

    def test_partial_failures(self, metrics):
        for i in range(10):
            status = TargetStatus.UP if i % 2 == 0 else TargetStatus.DOWN
            result = ProbeResult(
                target_id="t2",
                probe_type=ProbeType.TCP,
                status=status,
                response_time_ms=100,
                timestamp=time.time() - (9 - i) * 30,
            )
            metrics.record(result)

        metrics.flush_all()
        summary = metrics.get_uptime_summary("t2", hours=1)
        assert summary["uptime_pct"] == 50.0
