"""SQLite-based persistent storage for the HA agent."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from ha_agent.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
    ProbeResult,
    ProbeType,
    TargetStatus,
    UptimeRecord,
)

logger = logging.getLogger("ha_sentinel.storage")

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS probe_results (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    probe_type TEXT NOT NULL,
    status TEXT NOT NULL,
    response_time_ms REAL NOT NULL,
    timestamp REAL NOT NULL,
    message TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    UNIQUE(id)
);
CREATE INDEX IF NOT EXISTS idx_probe_target_ts ON probe_results(target_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_probe_status ON probe_results(status);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_name TEXT DEFAULT '',
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    started_at REAL NOT NULL,
    resolved_at REAL,
    acknowledged_at REAL,
    acknowledged_by TEXT,
    metadata TEXT DEFAULT '{}',
    remediation_attempts TEXT DEFAULT '[]',
    notification_log TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_incident_target ON incidents(target_id);
CREATE INDEX IF NOT EXISTS idx_incident_state ON incidents(state);
CREATE INDEX IF NOT EXISTS idx_incident_started ON incidents(started_at);

CREATE TABLE IF NOT EXISTS uptime_records (
    target_id TEXT NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    total_checks INTEGER DEFAULT 0,
    successful_checks INTEGER DEFAULT 0,
    avg_response_ms REAL DEFAULT 0,
    p95_response_ms REAL DEFAULT 0,
    p99_response_ms REAL DEFAULT 0,
    incidents_count INTEGER DEFAULT 0,
    PRIMARY KEY (target_id, period_start)
);

CREATE TABLE IF NOT EXISTS target_state (
    target_id TEXT PRIMARY KEY,
    current_status TEXT DEFAULT 'unknown',
    last_check_at REAL DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    consecutive_successes INTEGER DEFAULT 0,
    last_response_ms REAL DEFAULT 0,
    last_incident_id TEXT
);
"""


class Database:
    def __init__(self, data_dir: str = "./data/ha_sentinel") -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "ha_sentinel.db"
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            cur = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
        logger.info("Database initialized at %s", self._db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Probe Results --

    def save_probe_result(self, result: ProbeResult) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO probe_results
                   (id, target_id, probe_type, status, response_time_ms, timestamp, message, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.check_id,
                    result.target_id,
                    result.probe_type.value,
                    result.status.value,
                    result.response_time_ms,
                    result.timestamp,
                    result.message,
                    json.dumps(result.metadata),
                ),
            )

    def get_recent_results(
        self, target_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM probe_results
                   WHERE target_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (target_id, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    # -- Target State --

    def get_target_state(self, target_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT * FROM target_state WHERE target_id = ?", (target_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else {
                "target_id": target_id,
                "current_status": "unknown",
                "last_check_at": 0,
                "consecutive_failures": 0,
                "consecutive_successes": 0,
                "last_response_ms": 0,
                "last_incident_id": None,
            }

    def update_target_state(
        self,
        target_id: str,
        status: str,
        response_ms: float,
        consecutive_failures: int,
        consecutive_successes: int,
        incident_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO target_state
                   (target_id, current_status, last_check_at, consecutive_failures,
                    consecutive_successes, last_response_ms, last_incident_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    target_id,
                    status,
                    time.time(),
                    consecutive_failures,
                    consecutive_successes,
                    response_ms,
                    incident_id,
                ),
            )

    # -- Incidents --

    def save_incident(self, incident: Incident) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO incidents
                   (id, target_id, target_name, severity, state, title, description,
                    started_at, resolved_at, acknowledged_at, acknowledged_by,
                    metadata, remediation_attempts, notification_log)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    incident.id,
                    incident.target_id,
                    incident.target_name,
                    incident.severity.value,
                    incident.state.value,
                    incident.title,
                    incident.description,
                    incident.started_at,
                    incident.resolved_at,
                    incident.acknowledged_at,
                    incident.acknowledged_by,
                    json.dumps(incident.metadata),
                    json.dumps(incident.remediation_attempts),
                    json.dumps(incident.notification_log),
                ),
            )

    def get_open_incidents(self, target_id: str | None = None) -> list[Incident]:
        with self._conn() as conn:
            if target_id:
                cur = conn.execute(
                    """SELECT * FROM incidents
                       WHERE state IN ('open', 'acknowledged') AND target_id = ?
                       ORDER BY started_at DESC""",
                    (target_id,),
                )
            else:
                cur = conn.execute(
                    """SELECT * FROM incidents
                       WHERE state IN ('open', 'acknowledged')
                       ORDER BY started_at DESC"""
                )
            return [_row_to_incident(dict(row)) for row in cur.fetchall()]

    def get_incidents(
        self,
        limit: int = 100,
        offset: int = 0,
        target_id: str | None = None,
        state: str | None = None,
    ) -> list[Incident]:
        with self._conn() as conn:
            query = "SELECT * FROM incidents WHERE 1=1"
            params: list[Any] = []
            if target_id:
                query += " AND target_id = ?"
                params.append(target_id)
            if state:
                query += " AND state = ?"
                params.append(state)
            query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cur = conn.execute(query, params)
            return [_row_to_incident(dict(row)) for row in cur.fetchall()]

    def get_incident_by_id(self, incident_id: str) -> Incident | None:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
            row = cur.fetchone()
            return _row_to_incident(dict(row)) if row else None

    # -- Uptime Records --

    def save_uptime_record(self, record: UptimeRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO uptime_records
                   (target_id, period_start, period_end, total_checks,
                    successful_checks, avg_response_ms, p95_response_ms,
                    p99_response_ms, incidents_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.target_id,
                    record.period_start,
                    record.period_end,
                    record.total_checks,
                    record.successful_checks,
                    record.avg_response_ms,
                    record.p95_response_ms,
                    record.p99_response_ms,
                    record.incidents_count,
                ),
            )

    def get_uptime_records(
        self, target_id: str, since: float | None = None, limit: int = 720
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if since:
                cur = conn.execute(
                    """SELECT * FROM uptime_records
                       WHERE target_id = ? AND period_start >= ?
                       ORDER BY period_start DESC LIMIT ?""",
                    (target_id, since, limit),
                )
            else:
                cur = conn.execute(
                    """SELECT * FROM uptime_records
                       WHERE target_id = ?
                       ORDER BY period_start DESC LIMIT ?""",
                    (target_id, limit),
                )
            return [dict(row) for row in cur.fetchall()]

    # -- Cleanup --

    def cleanup_old_data(self, metrics_days: int = 90, incidents_days: int = 365) -> int:
        cutoff_metrics = time.time() - (metrics_days * 86400)
        cutoff_incidents = time.time() - (incidents_days * 86400)
        total = 0
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM probe_results WHERE timestamp < ?", (cutoff_metrics,)
            )
            total += cur.rowcount
            cur = conn.execute(
                "DELETE FROM uptime_records WHERE period_end < ?", (cutoff_metrics,)
            )
            total += cur.rowcount
            cur = conn.execute(
                "DELETE FROM incidents WHERE started_at < ? AND state IN ('resolved', 'auto_resolved')",
                (cutoff_incidents,),
            )
            total += cur.rowcount
        if total:
            logger.info("Cleaned up %d old records", total)
        return total

    def get_all_target_states(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM target_state ORDER BY target_id")
            return [dict(row) for row in cur.fetchall()]


def _row_to_incident(row: dict[str, Any]) -> Incident:
    return Incident(
        id=row["id"],
        target_id=row["target_id"],
        target_name=row.get("target_name", ""),
        severity=IncidentSeverity(row["severity"]),
        state=IncidentState(row["state"]),
        title=row["title"],
        description=row.get("description", ""),
        started_at=row["started_at"],
        resolved_at=row.get("resolved_at"),
        acknowledged_at=row.get("acknowledged_at"),
        acknowledged_by=row.get("acknowledged_by"),
        metadata=json.loads(row.get("metadata", "{}")),
        remediation_attempts=json.loads(row.get("remediation_attempts", "[]")),
        notification_log=json.loads(row.get("notification_log", "[]")),
    )
