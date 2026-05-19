"""Shared OpenRouter + Home Assistant conversation setup helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx

STRICT_PROMPT = (
    "You are a Home Assistant controller. "
    "Only control entities that exist. Never invent entities."
)


async def ws_request(base_url: str, access_token: str, command: dict[str, Any]) -> dict[str, Any]:
    import websockets

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/api/websocket"
    async with websockets.connect(ws_url, open_timeout=15) as websocket:
        await websocket.recv()
        await websocket.send(json.dumps({"type": "auth", "access_token": access_token}))
        auth_result = json.loads(await websocket.recv())
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError(f"WebSocket auth failed: {auth_result}")
        await websocket.send(json.dumps(command))
        return json.loads(await websocket.recv())


def run_ws(base_url: str, token: str, command: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(ws_request(base_url, token, command))


def api_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    if not path.startswith("/api/"):
        path = f"/api/{path.lstrip('/')}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Content-Type", "application/json")
    return httpx.request(method, f"{base_url}{path}", headers=headers, timeout=60, **kwargs)


def get_config_entries(base_url: str, token: str) -> list[dict[str, Any]]:
    response = api_request(base_url, token, "GET", "/api/config/config_entries/entry")
    response.raise_for_status()
    return response.json()


def find_openrouter_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("domain") == "open_router":
            return entry
    return None


def list_subentries(base_url: str, token: str, entry_id: str) -> list[dict[str, Any]]:
    result = run_ws(
        base_url,
        token,
        {
            "id": 1,
            "type": "config_entries/subentries/list",
            "entry_id": entry_id,
        },
    )
    return result.get("result", [])


def list_entity_registry(base_url: str, token: str) -> list[dict[str, Any]]:
    result = run_ws(base_url, token, {"id": 1, "type": "config/entity_registry/list"})
    return result.get("result", [])


def resolve_agent_for_subentry(base_url: str, token: str, subentry_id: str) -> str | None:
    for entry in list_entity_registry(base_url, token):
        if entry.get("config_subentry_id") == subentry_id and entry["entity_id"].startswith(
            "conversation."
        ):
            return entry["entity_id"]
    return None


def delete_subentry(base_url: str, token: str, entry_id: str, subentry_id: str) -> None:
    result = run_ws(
        base_url,
        token,
        {
            "id": 1,
            "type": "config_entries/subentries/delete",
            "entry_id": entry_id,
            "subentry_id": subentry_id,
        },
    )
    if not result.get("success"):
        raise RuntimeError(f"Failed to delete subentry {subentry_id}: {result}")


def start_subentry_flow(
    base_url: str,
    token: str,
    entry_id: str,
    subentry_type: str,
    subentry_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"handler": [entry_id, subentry_type]}
    if subentry_id:
        payload["subentry_id"] = subentry_id
    response = api_request(
        base_url,
        token,
        "POST",
        "/api/config/config_entries/subentries/flow",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def submit_subentry_flow(
    base_url: str,
    token: str,
    flow_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    response = api_request(
        base_url,
        token,
        "POST",
        f"/api/config/config_entries/subentries/flow/{flow_id}",
        json=data,
    )
    response.raise_for_status()
    return response.json()


def conversation_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "llm_hass_api": ["assist"],
        "prompt": STRICT_PROMPT,
        "web_search": False,
    }


def create_conversation_subentry(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
) -> str:
    flow = start_subentry_flow(base_url, token, entry_id, "conversation")
    result = submit_subentry_flow(base_url, token, flow["flow_id"], conversation_payload(model))
    if result.get("type") != "create_entry":
        raise RuntimeError(f"Unexpected conversation subentry result: {result}")
    return result["result"]["subentry_id"]


def reconfigure_conversation_subentry(
    base_url: str,
    token: str,
    entry_id: str,
    subentry_id: str,
    model: str,
) -> None:
    flow = start_subentry_flow(
        base_url,
        token,
        entry_id,
        "conversation",
        subentry_id=subentry_id,
    )
    result = submit_subentry_flow(
        base_url,
        token,
        flow["flow_id"],
        conversation_payload(model),
    )
    if result.get("type") not in {"abort", "create_entry"}:
        raise RuntimeError(f"Unexpected conversation reconfigure result: {result}")


def dedupe_conversation_subentries(
    base_url: str,
    token: str,
    entry_id: str,
    *,
    keep_subentry_id: str | None = None,
) -> list[dict[str, Any]]:
    conversation_subentries = [
        subentry
        for subentry in list_subentries(base_url, token, entry_id)
        if subentry.get("subentry_type") == "conversation"
    ]
    if len(conversation_subentries) <= 1:
        return conversation_subentries

    if keep_subentry_id:
        keep = next(
            (subentry for subentry in conversation_subentries if subentry["subentry_id"] == keep_subentry_id),
            conversation_subentries[-1],
        )
    else:
        keep = conversation_subentries[-1]

    for subentry in conversation_subentries:
        if subentry["subentry_id"] == keep["subentry_id"]:
            continue
        delete_subentry(base_url, token, entry_id, subentry["subentry_id"])
    return [keep]


def configure_openrouter_conversation(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
    *,
    preferred_subentry_id: str | None = None,
    dedupe: bool = True,
) -> tuple[str, str]:
    conversation_subentries = [
        subentry
        for subentry in list_subentries(base_url, token, entry_id)
        if subentry.get("subentry_type") == "conversation"
    ]

    if dedupe and len(conversation_subentries) > 1:
        conversation_subentries = dedupe_conversation_subentries(
            base_url,
            token,
            entry_id,
            keep_subentry_id=preferred_subentry_id,
        )

    if conversation_subentries:
        subentry_id = conversation_subentries[0]["subentry_id"]
        reconfigure_conversation_subentry(base_url, token, entry_id, subentry_id, model)
    else:
        subentry_id = create_conversation_subentry(base_url, token, entry_id, model)

    agent_id = resolve_agent_for_subentry(base_url, token, subentry_id)
    if agent_id is None:
        raise RuntimeError(
            f"No conversation agent entity found for OpenRouter subentry {subentry_id}"
        )
    return subentry_id, agent_id
