"""Tests for HA-SentinelAI REST API."""

import asyncio
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from ha_agent.config import AgentConfig
from ha_agent.models import MonitorTarget, ProbeType
from ha_agent.agent import SentinelAgent
from ha_agent.api.server import APIServer


@pytest.fixture
def agent_config(tmp_path):
    return AgentConfig(
        data_dir=str(tmp_path / "data"),
        api_enabled=False,
        targets=[
            MonitorTarget(
                id="test_http",
                name="Test HTTP",
                probe_type=ProbeType.HTTP,
                endpoint="https://example.com",
                group="test",
            ),
        ],
    )


@pytest.fixture
def agent(agent_config):
    return SentinelAgent(config=agent_config)


@pytest.fixture
def api_app(agent):
    server = APIServer(agent=agent, host="127.0.0.1", port=0, secret="")
    return server._app


class TestAPIEndpoints:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_status_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/status")
        assert resp.status == 200
        data = await resp.json()
        assert "overall_status" in data
        assert "targets" in data
        assert len(data["targets"]) == 1

    @pytest.mark.asyncio
    async def test_targets_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/targets")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["id"] == "test_http"

    @pytest.mark.asyncio
    async def test_target_detail(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/targets/test_http")
        assert resp.status == 200
        data = await resp.json()
        assert data["target"]["name"] == "Test HTTP"
        assert "uptime" in data

    @pytest.mark.asyncio
    async def test_target_not_found(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/targets/nonexistent")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_incidents_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/incidents")
        assert resp.status == 200
        data = await resp.json()
        assert "incidents" in data

    @pytest.mark.asyncio
    async def test_uptime_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/uptime?hours=24")
        assert resp.status == 200
        data = await resp.json()
        assert data["period_hours"] == 24

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/api/v1/metrics")
        assert resp.status == 200
        data = await resp.json()
        assert "targets_monitored" in data
        assert data["targets_monitored"] == 1

    @pytest.mark.asyncio
    async def test_status_page_html(self, aiohttp_client, api_app):
        client = await aiohttp_client(api_app)
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "HA-SentinelAI" in text
        assert "Test HTTP" in text


class TestAPIAuth:
    @pytest.mark.asyncio
    async def test_auth_required_for_protected_routes(self, aiohttp_client, agent):
        server = APIServer(agent=agent, host="127.0.0.1", port=0, secret="mysecret")
        client = await aiohttp_client(server._app)

        resp = await client.get("/api/v1/targets")
        assert resp.status == 401

        resp = await client.get("/api/v1/targets", headers={"Authorization": "Bearer mysecret"})
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_public_routes_no_auth(self, aiohttp_client, agent):
        server = APIServer(agent=agent, host="127.0.0.1", port=0, secret="mysecret")
        client = await aiohttp_client(server._app)

        for path in ["/", "/health", "/api/v1/status"]:
            resp = await client.get(path)
            assert resp.status == 200, f"Expected 200 for {path}, got {resp.status}"
