"""Canonical data models used across the HA-SentinelAI agent."""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class TargetStatus(enum.Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    MAINTENANCE = "maintenance"


class IncidentSeverity(enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


class IncidentState(enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    AUTO_RESOLVED = "auto_resolved"


class ProbeType(enum.Enum):
    HTTP = "http"
    TCP = "tcp"
    DNS = "dns"
    SSL = "ssl"
    ICMP = "icmp"
    CUSTOM = "custom"
    DOCKER = "docker"
    PROCESS = "process"


@dataclass
class ProbeResult:
    target_id: str
    probe_type: ProbeType
    status: TargetStatus
    response_time_ms: float
    timestamp: float = field(default_factory=time.time)
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    check_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def is_healthy(self) -> bool:
        return self.status in (TargetStatus.UP, TargetStatus.MAINTENANCE)


@dataclass
class MonitorTarget:
    id: str
    name: str
    probe_type: ProbeType
    endpoint: str
    interval_seconds: int = 30
    timeout_seconds: int = 10
    retries: int = 2
    expected_status_codes: list[int] = field(default_factory=lambda: [200])
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "GET"
    body: str | None = None
    tags: list[str] = field(default_factory=list)
    group: str = "default"
    enabled: bool = True

    # Thresholds
    response_time_warn_ms: float = 1000.0
    response_time_crit_ms: float = 5000.0
    consecutive_failures_warn: int = 2
    consecutive_failures_crit: int = 3

    # SSL-specific
    ssl_warn_days: int = 30
    ssl_crit_days: int = 7

    # DNS-specific
    dns_record_type: str = "A"
    dns_expected_values: list[str] = field(default_factory=list)
    dns_server: str | None = None

    # Auto-remediation
    remediation_enabled: bool = False
    remediation_actions: list[dict[str, Any]] = field(default_factory=list)
    remediation_cooldown_seconds: int = 300

    # Notification overrides
    notification_channels: list[str] = field(default_factory=list)


@dataclass
class Incident:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    target_id: str = ""
    target_name: str = ""
    severity: IncidentSeverity = IncidentSeverity.WARNING
    state: IncidentState = IncidentState.OPEN
    title: str = ""
    description: str = ""
    started_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    acknowledged_at: float | None = None
    acknowledged_by: str | None = None
    probe_results: list[ProbeResult] = field(default_factory=list)
    remediation_attempts: list[dict[str, Any]] = field(default_factory=list)
    notification_log: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        end = self.resolved_at or time.time()
        return end - self.started_at

    def resolve(self, auto: bool = False) -> None:
        self.state = IncidentState.AUTO_RESOLVED if auto else IncidentState.RESOLVED
        self.resolved_at = time.time()

    def acknowledge(self, by: str = "system") -> None:
        self.state = IncidentState.ACKNOWLEDGED
        self.acknowledged_at = time.time()
        self.acknowledged_by = by


@dataclass
class UptimeRecord:
    target_id: str
    period_start: float
    period_end: float
    total_checks: int = 0
    successful_checks: int = 0
    avg_response_ms: float = 0.0
    p95_response_ms: float = 0.0
    p99_response_ms: float = 0.0
    incidents_count: int = 0

    @property
    def uptime_pct(self) -> float:
        if self.total_checks == 0:
            return 100.0
        return (self.successful_checks / self.total_checks) * 100.0
