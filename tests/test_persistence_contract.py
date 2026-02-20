from __future__ import annotations

import pytest

from src.data.es_client import ESClient
from src.execution.executor import TradeExecutor


class _FakeESBackend:
    def __init__(self) -> None:
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"hits": {"hits": [{"_source": {"ok": True}}]}}


class _FakeESSink:
    def __init__(self) -> None:
        self.calls = []

    def enqueue(self, doc_type, doc, doc_id=None, timestamp=None):
        self.calls.append(
            {
                "doc_type": doc_type,
                "doc": doc,
                "doc_id": doc_id,
                "timestamp": timestamp,
            }
        )


@pytest.mark.asyncio
async def test_es_search_blocks_ledger_doc_types():
    client = ESClient(hosts=["http://localhost:9200"])
    backend = _FakeESBackend()
    client._es = backend

    results = await client.search("trades", {"query": {"match_all": {}}}, size=5)

    assert results == []
    assert backend.calls == []


@pytest.mark.asyncio
async def test_es_search_allows_analytics_doc_types():
    client = ESClient(hosts=["http://localhost:9200"])
    backend = _FakeESBackend()
    client._es = backend

    results = await client.search("orderbook", {"query": {"match_all": {}}}, size=2)

    assert results == [{"ok": True}]
    assert len(backend.calls) == 1
    assert backend.calls[0]["index"] == "novapulse-orderbook-*"


def test_trade_event_es_docs_are_marked_non_canonical(monkeypatch):
    sink = _FakeESSink()
    executor = TradeExecutor.__new__(TradeExecutor)
    executor.es_client = sink
    monkeypatch.setattr("src.execution.executor.time.time", lambda: 1_700_000_000.0)

    executor._enqueue_trade_event(
        "opened",
        {"trade_id": "trade-123", "pair": "BTC/USD", "status": "open"},
    )

    assert len(sink.calls) == 1
    call = sink.calls[0]
    assert call["doc_type"] == "trades"
    assert call["doc_id"] == "trade-123:opened:1700000000"
    assert call["doc"]["canonical_source"] == "sqlite"
    assert call["doc"]["analytics_mirror"] is True

