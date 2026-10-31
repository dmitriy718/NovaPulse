"""Tests for HA-SentinelAI monitoring probes."""

import asyncio
import pytest

from ha_agent.models import MonitorTarget, ProbeType, TargetStatus
from ha_agent.probes.http_probe import HTTPProbe
from ha_agent.probes.tcp_probe import TCPProbe, _parse_host_port
from ha_agent.probes.dns_probe import DNSProbe
from ha_agent.probes.icmp_probe import ICMPProbe
from ha_agent.probes.custom_probe import CustomProbe
from ha_agent.probes.ssl_probe import _parse_ssl_endpoint, _parse_ssl_date


def _make_target(probe_type: ProbeType, endpoint: str, **kw) -> MonitorTarget:
    return MonitorTarget(
        id="test_target",
        name="Test Target",
        probe_type=probe_type,
        endpoint=endpoint,
        timeout_seconds=kw.pop("timeout_seconds", 5),
        retries=kw.pop("retries", 1),
        **kw,
    )


class TestTCPParsing:
    def test_host_port(self):
        assert _parse_host_port("example.com:443") == ("example.com", 443)

    def test_host_only(self):
        assert _parse_host_port("example.com") == ("example.com", 80)

    def test_with_prefix(self):
        assert _parse_host_port("tcp://host:8080") == ("host", 8080)


class TestSSLParsing:
    def test_https_endpoint(self):
        assert _parse_ssl_endpoint("https://example.com") == ("example.com", 443)

    def test_ssl_endpoint_with_port(self):
        assert _parse_ssl_endpoint("ssl://host:8443") == ("host", 8443)

    def test_parse_ssl_date(self):
        dt = _parse_ssl_date("Jan 15 12:00:00 2030 GMT")
        assert dt is not None
        assert dt.year == 2030


class TestCustomProbe:
    @pytest.mark.asyncio
    async def test_success_command(self):
        target = _make_target(ProbeType.CUSTOM, "echo hello")
        probe = CustomProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.UP
        assert "hello" in result.message

    @pytest.mark.asyncio
    async def test_failing_command(self):
        target = _make_target(ProbeType.CUSTOM, "exit 2")
        probe = CustomProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.DOWN

    @pytest.mark.asyncio
    async def test_warning_command(self):
        target = _make_target(ProbeType.CUSTOM, "exit 1")
        probe = CustomProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_json_output_parsing(self):
        target = _make_target(ProbeType.CUSTOM, 'echo \'{"status":"ok","value":42}\'')
        probe = CustomProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.UP
        assert result.metadata.get("value") == 42


class TestDNSProbe:
    @pytest.mark.asyncio
    async def test_resolve_known_host(self):
        target = _make_target(ProbeType.DNS, "dns://google.com", dns_record_type="A")
        probe = DNSProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.UP
        assert result.metadata.get("hostname") == "google.com"

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self):
        target = _make_target(
            ProbeType.DNS,
            "dns://this-domain-does-not-exist-xyz123.invalid",
            dns_record_type="A",
        )
        probe = DNSProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.DOWN


class TestICMPProbe:
    @pytest.mark.asyncio
    async def test_ping_localhost(self):
        target = _make_target(ProbeType.ICMP, "icmp://127.0.0.1")
        probe = ICMPProbe()
        result = await probe.execute(target)
        assert result.status == TargetStatus.UP
        assert result.metadata.get("packet_loss_pct") == 0


class TestHTTPProbe:
    @pytest.mark.asyncio
    async def test_unreachable_endpoint_with_retries(self):
        target = _make_target(
            ProbeType.HTTP,
            "http://192.0.2.1:1",
            timeout_seconds=2,
            retries=1,
        )
        probe = HTTPProbe()
        try:
            result = await probe.execute_with_retries(target)
            assert result.status == TargetStatus.DOWN
        finally:
            await probe.close()

    @pytest.mark.asyncio
    async def test_probe_result_fields(self):
        target = _make_target(
            ProbeType.HTTP,
            "http://192.0.2.1:1",
            timeout_seconds=2,
            retries=1,
        )
        probe = HTTPProbe()
        try:
            result = await probe.execute_with_retries(target)
            assert result.target_id == "test_target"
            assert result.probe_type == ProbeType.HTTP
        finally:
            await probe.close()


class TestTCPProbe:
    @pytest.mark.asyncio
    async def test_unreachable_port(self):
        # Use localhost on a port that's very unlikely to be open
        target = _make_target(ProbeType.TCP, "127.0.0.1:19", timeout_seconds=2)
        probe = TCPProbe()
        result = await probe.execute(target)
        # Port 19 (chargen) is almost certainly closed/refused on localhost
        assert result.target_id == "test_target"
        assert result.probe_type == ProbeType.TCP
