"""Qloo taste-intelligence tools (read-only).

Built for the Qloo Agentic Hackathon: exposes Qloo's measured
cross-domain affinities to the agent as a `get_affinity` tool, so
recommendations it drafts are grounded in real cultural-affinity
data instead of the model's guesses.

Live calls need `QLOO_API_KEY` (hackathon keys default to
`https://hackathon.api.qloo.com`; override with `QLOO_API_BASE`).
Without a key the tool returns a clear error instead of pretending
to succeed, so the agent never hallucinates affinity data.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from app.schemas.tools import PermissionLevel, ToolKind

QLOO_API_BASE = "https://hackathon.api.qloo.com"


class GetAffinityInput(BaseModel):
    entity_query: str = Field(
        ..., description="Name of the entity to anchor on, e.g. a restaurant, brand or film."
    )
    result_type: str = Field(
        default="urn:entity:brand",
        description="Qloo entity type to return, e.g. urn:entity:brand, urn:entity:place, urn:entity:movie.",
    )
    location_query: Optional[str] = Field(
        default=None, description="Optional natural-language region, e.g. 'Pune' or 'New York'."
    )
    take: int = Field(default=10, ge=1, le=20, description="How many affinity results to return (1-20).")


class _QlooClient:
    """Thin httpx wrapper around Qloo's /search and /v2/insights endpoints."""

    def __init__(self, api_key: str, base_url: str = QLOO_API_BASE, transport: Optional[httpx.BaseTransport] = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def _headers(self) -> Dict[str, str]:
        return {"accept": "application/json", "x-api-key": self._api_key}

    async def resolve_entity(self, query: str, result_type: str) -> Optional[str]:
        """Return the entity_id of the best /search match for `query`."""
        url = f"{self._base_url}/search"
        async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
            resp = await client.get(
                url,
                params={"query": query, "types": result_type, "take": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            body = resp.json()
        entities = (body.get("results") or {}).get("entities") or []
        if not entities:
            return None
        return entities[0].get("entity_id")

    async def insights(
        self,
        result_type: str,
        signal_entity_id: str,
        take: int,
        location_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query /v2/insights for entities with high affinity to the anchor entity."""
        params: Dict[str, Any] = {
            "filter.type": result_type,
            "signal.interests.entities": signal_entity_id,
            "take": take,
        }
        if location_query:
            params["signal.location.query"] = location_query
        url = f"{self._base_url}/v2/insights/"
        async with httpx.AsyncClient(timeout=20.0, transport=self._transport) as client:
            resp = await client.get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            body = resp.json()
        entities = (body.get("results") or {}).get("entities") or []
        results: List[Dict[str, Any]] = []
        for entity in entities:
            props = entity.get("properties") or {}
            results.append(
                {
                    "name": entity.get("name") or props.get("name"),
                    "entity_id": entity.get("entity_id"),
                    "affinity": entity.get("affinity"),
                    "subtype": entity.get("subtype"),
                }
            )
        return results


async def get_affinity(
    args: GetAffinityInput, *, client: Optional[_QlooClient] = None
) -> Dict[str, Any]:
    """Resolve the anchor entity and return its top cross-domain affinities."""
    qloo = client or _make_client()
    entity_id = await qloo.resolve_entity(args.entity_query, args.result_type)
    if entity_id is None:
        return {
            "success": False,
            "error": f"No Qloo entity found for query '{args.entity_query}'.",
        }
    entities = await qloo.insights(
        args.result_type, entity_id, args.take, args.location_query
    )
    return {
        "success": True,
        "anchor_entity_id": entity_id,
        "results": entities,
    }


def _make_client() -> _QlooClient:
    api_key = os.environ.get("QLOO_API_KEY")
    if not api_key:
        raise RuntimeError(
            "QLOO_API_KEY is not set; get_affinity cannot reach Qloo. "
            "Set the key (or inject a client in tests) instead of guessing affinities."
        )
    return _QlooClient(api_key, os.environ.get("QLOO_API_BASE") or QLOO_API_BASE)


def register_qloo_tools(reg) -> None:
    from app.tools.registry import ToolDefinition

    reg.register(
        ToolDefinition(
            name="get_affinity",
            description=(
                "Look up Qloo cross-domain affinities: given an entity (restaurant, "
                "brand, film, ...), return related entities ranked by measured "
                "affinity. Grounds recommendations in real taste data."
            ),
            input_model=GetAffinityInput,
            kind=ToolKind.READ,
            permission=PermissionLevel.VIEW,
            handler=get_affinity,
        )
    )
