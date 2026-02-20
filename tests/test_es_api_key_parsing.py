import asyncio
import sys
import types

import pytest

from src.data.es_client import ESClient


class _FakeES:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeES.last_kwargs = kwargs

    async def info(self):
        return {"version": {"number": "8.17.0", "build_flavor": "default"}}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_es_client_accepts_raw_id_colon_key(monkeypatch):
    monkeypatch.setitem(sys.modules, "elasticsearch", types.SimpleNamespace(AsyncElasticsearch=_FakeES))

    client = ESClient(hosts=["https://example.invalid:9200"], api_key="abc123:def456")

    async def _noop_templates():
        return None

    async def _noop_flush():
        await asyncio.sleep(3600)

    monkeypatch.setattr(client, "_create_index_templates", _noop_templates)
    monkeypatch.setattr(client, "_flush_loop", _noop_flush)

    ok = await client.connect()
    assert ok is True
    assert _FakeES.last_kwargs["api_key"] == ("abc123", "def456")

    await client.close()
