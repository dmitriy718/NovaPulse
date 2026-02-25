"""YAML-based configuration loader with validation and hot-reload support."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ha_agent.models import MonitorTarget, ProbeType

logger = logging.getLogger("ha_sentinel.config")

_ENV_PREFIX = "HA_SENTINEL_"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(f"{_ENV_PREFIX}{key}", default)


@dataclass
class NotificationChannelConfig:
    channel_type: str = ""
    name: str = ""
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfig:
    agent_name: str = "HA-SentinelAI"
    log_level: str = "INFO"
    data_dir: str = "./data/ha_sentinel"
    check_jitter_seconds: int = 5

    # API server
    api_enabled: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8089
    api_secret: str = ""

    # Targets
    targets: list[MonitorTarget] = field(default_factory=list)

    # Notification channels
    notification_channels: list[NotificationChannelConfig] = field(default_factory=list)

    # Global notification settings
    notification_cooldown_seconds: int = 300
    escalation_after_minutes: int = 15

    # Metrics retention
    metrics_retention_days: int = 90
    incident_retention_days: int = 365

    # Auto-remediation global toggle
    remediation_enabled: bool = True
    max_remediation_per_hour: int = 10

    # Heartbeat / self-monitoring
    heartbeat_url: str = ""
    heartbeat_interval_seconds: int = 60


def _parse_target(raw: dict[str, Any]) -> MonitorTarget:
    probe_type = ProbeType(raw.get("probe_type", raw.get("type", "http")))
    return MonitorTarget(
        id=raw.get("id", raw.get("name", "unknown").lower().replace(" ", "_")),
        name=raw.get("name", "Unknown"),
        probe_type=probe_type,
        endpoint=raw.get("endpoint", raw.get("url", raw.get("host", ""))),
        interval_seconds=int(raw.get("interval_seconds", raw.get("interval", 30))),
        timeout_seconds=int(raw.get("timeout_seconds", raw.get("timeout", 10))),
        retries=int(raw.get("retries", 2)),
        expected_status_codes=raw.get("expected_status_codes", [200]),
        headers=raw.get("headers", {}),
        method=raw.get("method", "GET"),
        body=raw.get("body"),
        tags=raw.get("tags", []),
        group=raw.get("group", "default"),
        enabled=raw.get("enabled", True),
        response_time_warn_ms=float(raw.get("response_time_warn_ms", 1000)),
        response_time_crit_ms=float(raw.get("response_time_crit_ms", 5000)),
        consecutive_failures_warn=int(raw.get("consecutive_failures_warn", 2)),
        consecutive_failures_crit=int(raw.get("consecutive_failures_crit", 3)),
        ssl_warn_days=int(raw.get("ssl_warn_days", 30)),
        ssl_crit_days=int(raw.get("ssl_crit_days", 7)),
        dns_record_type=raw.get("dns_record_type", "A"),
        dns_expected_values=raw.get("dns_expected_values", []),
        dns_server=raw.get("dns_server"),
        remediation_enabled=raw.get("remediation_enabled", False),
        remediation_actions=raw.get("remediation_actions", []),
        remediation_cooldown_seconds=int(raw.get("remediation_cooldown_seconds", 300)),
        notification_channels=raw.get("notification_channels", []),
    )


def _parse_notification(raw: dict[str, Any]) -> NotificationChannelConfig:
    return NotificationChannelConfig(
        channel_type=raw.get("type", ""),
        name=raw.get("name", ""),
        enabled=raw.get("enabled", True),
        config=raw.get("config", {}),
    )


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Load config from YAML file with environment variable overrides."""
    if path is None:
        path = _env("CONFIG_PATH", "ha_config.yaml")
    path = Path(path)

    raw: dict[str, Any] = {}
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        logger.info("Loaded config from %s", path)
    else:
        logger.warning("Config file %s not found, using defaults", path)

    agent_raw = raw.get("agent", {})
    cfg = AgentConfig(
        agent_name=agent_raw.get("name", _env("NAME", "HA-SentinelAI")),
        log_level=agent_raw.get("log_level", _env("LOG_LEVEL", "INFO")),
        data_dir=agent_raw.get("data_dir", _env("DATA_DIR", "./data/ha_sentinel")),
        check_jitter_seconds=int(agent_raw.get("check_jitter_seconds", 5)),
        api_enabled=agent_raw.get("api", {}).get(
            "enabled", _env("API_ENABLED", "true").lower() == "true"
        ),
        api_host=agent_raw.get("api", {}).get("host", _env("API_HOST", "0.0.0.0")),
        api_port=int(agent_raw.get("api", {}).get("port", _env("API_PORT", "8089"))),
        api_secret=agent_raw.get("api", {}).get("secret", _env("API_SECRET", "")),
        notification_cooldown_seconds=int(
            agent_raw.get("notification_cooldown_seconds", 300)
        ),
        escalation_after_minutes=int(agent_raw.get("escalation_after_minutes", 15)),
        metrics_retention_days=int(agent_raw.get("metrics_retention_days", 90)),
        incident_retention_days=int(agent_raw.get("incident_retention_days", 365)),
        remediation_enabled=agent_raw.get("remediation_enabled", True),
        max_remediation_per_hour=int(agent_raw.get("max_remediation_per_hour", 10)),
        heartbeat_url=agent_raw.get("heartbeat_url", _env("HEARTBEAT_URL", "")),
        heartbeat_interval_seconds=int(
            agent_raw.get("heartbeat_interval_seconds", 60)
        ),
    )

    for t in raw.get("targets", []):
        try:
            cfg.targets.append(_parse_target(t))
        except Exception as exc:
            logger.error("Failed to parse target %s: %s", t.get("name", "?"), exc)

    for n in raw.get("notifications", []):
        try:
            cfg.notification_channels.append(_parse_notification(n))
        except Exception as exc:
            logger.error("Failed to parse notification %s: %s", n.get("name", "?"), exc)

    return cfg
