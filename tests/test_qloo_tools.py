"""Tests for the Qloo affinity tool (mocked transport, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.tools.qloo_tools import GetAffinityInput, _QlooClient, get_affinity


def _client(handler) -> _QlooClient:
    return _QlooClient(
        api_key="test-key",
        base_url="https://qloo.test",
        transport=httpx.MockTransport(handler),
    )


def _mock(responses):
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    return handler


@pytest.mark.asyncio
async def test_get_affinity_happy_path():
    search_body = {"results": {"entities": [{"entity_id": "E-123", "name": "Balthazar"}]}}
    insights_body = {
        "success": True,
        "results": {
            "entities": [
                {"name": "Jack's Wife Freda", "entity_id": "E-9", "affinity": 0.91,
                 "subtype": "urn:entity:place"},
                {"name": "Ruby's Cafe", "entity_id": "E-8", "affinity": 0.83,
                 "subtype": "urn:entity:place"},
            ]
        },
    }
    client = _client(
        _mock(
            [
                httpx.Response(200, json=search_body),
                httpx.Response(200, json=insights_body),
            ]
        )
    )
    out = await get_affinity(GetAffinityInput(entity_query="Balthazar"), client=client)
    assert out["success"] is True
    assert out["anchor_entity_id"] == "E-123"
    assert out["results"][0]["name"] == "Jack's Wife Freda"
    assert out["results"][0]["affinity"] == 0.91


@pytest.mark.asyncio
async def test_get_affinity_no_entity_found():
    client = _client(_mock([httpx.Response(200, json={"results": {"entities": []}})]))
    out = await get_affinity(GetAffinityInput(entity_query="zzz-nonexistent"), client=client)
    assert out["success"] is False
    assert "No Qloo entity found" in out["error"]


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    monkeypatch.delenv("QLOO_API_BASE", raising=False)
    import app.tools.qloo_tools as q
    with pytest.raises(RuntimeError) as err:
        q._make_client()
    assert "QLOO_API_KEY" in str(err.value)


def test_tool_registered():
    from app.tools.registry import get_registry

    reg = get_registry()
    tool = reg.get("get_affinity")
    assert tool is not None
    assert tool.kind.value == "read"
    schema = tool.input_model.model_json_schema()
    assert "entity_query" in schema["properties"]
