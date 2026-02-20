from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api.server import DashboardServer
from src.data.es_client import ESClient


def test_es_client_tracks_dropped_docs_when_buffer_overflows():
    client = ESClient(hosts=["http://localhost:9200"], buffer_maxlen=3)
    client._es = object()  # enable enqueue path without connecting

    for i in range(5):
        client.enqueue("market", {"seq": i})

    assert client.queue_capacity == 3
    assert client.queue_depth == 3
    assert client.dropped_docs == 2
    assert [item["_source"]["seq"] for item in list(client._buffer)] == [2, 3, 4]


def test_status_includes_es_queue_metrics():
    class _FakeWS:
        is_connected = True

    class _FakeES:
        connected = True
        queue_depth = 7
        queue_capacity = 50
        dropped_docs = 4

    class _FakeEngine:
        def __init__(self):
            self._running = True
            self._trading_paused = False
            self._scan_count = 12
            self.pairs = ["BTC/USD"]
            self.mode = "paper"
            self._start_time = time.time() - 120
            self.scan_interval = 60
            self.ws_client = _FakeWS()
            self._auto_pause_reason = ""
            self.exchange_name = "kraken"
            self.tenant_id = "default"
            self.es_client = _FakeES()
            self.config = SimpleNamespace(
                dashboard=SimpleNamespace(
                    rate_limit_enabled=False,
                    require_api_key_for_reads=False,
                ),
                app=SimpleNamespace(mode="paper"),
                billing=SimpleNamespace(
                    tenant=SimpleNamespace(default_tenant_id="default"),
                ),
            )

    server = DashboardServer()
    server._admin_key = "ADMIN"
    server._bot_engine = _FakeEngine()
    api = TestClient(server.app)

    resp = api.get("/api/v1/status", headers={"X-API-Key": "ADMIN"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["es_queue"] == {
        "engines_with_es": 1,
        "connected": 1,
        "depth": 7,
        "capacity": 50,
        "dropped_docs": 4,
    }
