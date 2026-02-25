"""Tests for HA-SentinelAI configuration loading."""

import os
import tempfile
import pytest
import yaml

from ha_agent.config import load_config, AgentConfig
from ha_agent.models import ProbeType


class TestLoadConfig:
    def test_load_from_yaml(self, tmp_path):
        config_data = {
            "agent": {
                "name": "TestAgent",
                "log_level": "DEBUG",
                "api": {"enabled": False, "port": 9999},
            },
            "targets": [
                {
                    "name": "Test HTTP",
                    "id": "test_http",
                    "type": "http",
                    "endpoint": "https://example.com",
                    "interval_seconds": 60,
                },
                {
                    "name": "Test TCP",
                    "id": "test_tcp",
                    "type": "tcp",
                    "endpoint": "example.com:443",
                },
            ],
            "notifications": [
                {
                    "name": "test-slack",
                    "type": "slack",
                    "config": {"webhook_url": "https://hooks.slack.com/test"},
                },
            ],
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        cfg = load_config(str(config_file))
        assert cfg.agent_name == "TestAgent"
        assert cfg.log_level == "DEBUG"
        assert cfg.api_enabled is False
        assert cfg.api_port == 9999
        assert len(cfg.targets) == 2
        assert cfg.targets[0].probe_type == ProbeType.HTTP
        assert cfg.targets[0].endpoint == "https://example.com"
        assert cfg.targets[1].probe_type == ProbeType.TCP
        assert len(cfg.notification_channels) == 1
        assert cfg.notification_channels[0].channel_type == "slack"

    def test_missing_config_uses_defaults(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.agent_name == "HA-SentinelAI"
        assert cfg.api_port == 8089
        assert len(cfg.targets) == 0

    def test_all_probe_types_parsed(self, tmp_path):
        targets = []
        for pt in ["http", "tcp", "dns", "ssl", "icmp", "docker", "process", "custom"]:
            targets.append({
                "name": f"Test {pt}",
                "id": f"test_{pt}",
                "type": pt,
                "endpoint": f"test_{pt}_endpoint",
            })

        config_file = tmp_path / "types.yaml"
        with open(config_file, "w") as f:
            yaml.dump({"targets": targets}, f)

        cfg = load_config(str(config_file))
        assert len(cfg.targets) == 8
        types_found = {t.probe_type for t in cfg.targets}
        assert types_found == {
            ProbeType.HTTP, ProbeType.TCP, ProbeType.DNS, ProbeType.SSL,
            ProbeType.ICMP, ProbeType.DOCKER, ProbeType.PROCESS, ProbeType.CUSTOM,
        }

    def test_target_with_remediation(self, tmp_path):
        config_data = {
            "targets": [{
                "name": "With Remediation",
                "id": "rem_test",
                "type": "http",
                "endpoint": "https://example.com",
                "remediation_enabled": True,
                "remediation_actions": [
                    {"type": "restart_docker", "container": "myapp"},
                ],
                "remediation_cooldown_seconds": 600,
            }],
        }
        config_file = tmp_path / "rem.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        cfg = load_config(str(config_file))
        assert cfg.targets[0].remediation_enabled is True
        assert len(cfg.targets[0].remediation_actions) == 1
        assert cfg.targets[0].remediation_cooldown_seconds == 600
