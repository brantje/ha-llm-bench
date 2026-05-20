"""Shared OpenRouter + Home Assistant conversation setup helpers."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import httpx

CONFIG_ENTRY_LOAD_TIMEOUT = 120
SUBENTRY_FLOW_RETRIES = 5
SUBENTRY_FLOW_RETRY_DELAY = 2.0

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


def wait_for_config_entry_loaded(
    base_url: str,
    token: str,
    entry_id: str,
    timeout: float = CONFIG_ENTRY_LOAD_TIMEOUT,
) -> dict[str, Any]:
    """Wait until a config entry reaches the loaded state (required for subentry flows)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in get_config_entries(base_url, token):
            if entry["entry_id"] == entry_id and entry.get("state") == "loaded":
                return entry
        time.sleep(1)
    raise TimeoutError(
        f"Config entry {entry_id} did not reach 'loaded' within {timeout:.0f}s"
    )


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


def _subentry_flow_succeeded(result: dict[str, Any]) -> bool:
    if result.get("type") == "create_entry":
        return True
    return (
        result.get("type") == "abort"
        and result.get("reason") == "reconfigure_successful"
    )


def run_conversation_subentry_flow(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
    *,
    subentry_id: str | None = None,
) -> dict[str, Any]:
    """Start and complete an OpenRouter conversation subentry user/reconfigure flow."""
    wait_for_config_entry_loaded(base_url, token, entry_id)
    last_error: Exception | None = None

    for attempt in range(SUBENTRY_FLOW_RETRIES):
        try:
            started = start_subentry_flow(
                base_url,
                token,
                entry_id,
                "conversation",
                subentry_id=subentry_id,
            )
            flow_type = started.get("type")

            if flow_type == "abort":
                reason = started.get("reason", "unknown")
                if reason == "entry_not_loaded":
                    wait_for_config_entry_loaded(base_url, token, entry_id)
                    last_error = RuntimeError(f"Subentry flow aborted: {reason}")
                    time.sleep(SUBENTRY_FLOW_RETRY_DELAY)
                    continue
                if reason == "reconfigure_successful":
                    return started
                raise RuntimeError(f"Subentry flow aborted: {reason}")

            if flow_type == "create_entry":
                return started

            if flow_type != "form":
                raise RuntimeError(f"Unexpected subentry flow start: {started}")

            flow_id = started.get("flow_id")
            if not flow_id:
                raise RuntimeError(f"Subentry flow missing flow_id: {started}")

            result = submit_subentry_flow(
                base_url, token, flow_id, conversation_payload(model)
            )
            if _subentry_flow_succeeded(result):
                return result
            raise RuntimeError(f"Unexpected subentry flow result: {result}")

        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 404:
                wait_for_config_entry_loaded(base_url, token, entry_id)
                time.sleep(SUBENTRY_FLOW_RETRY_DELAY)
                continue
            raise

    raise RuntimeError(
        f"Conversation subentry flow failed after {SUBENTRY_FLOW_RETRIES} attempts"
    ) from last_error


def _normalize_for_match(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _model_match_keys(model: str) -> set[str]:
    keys = {_normalize_for_match(model)}
    if "/" in model:
        slug = model.rsplit("/", 1)[-1]
        keys.add(_normalize_for_match(slug))
        keys.add(_normalize_for_match(slug.replace(":free", "")))
    return {key for key in keys if key}


def models_match(left: str, right: str) -> bool:
    right_norm = _normalize_for_match(right)
    if not right_norm:
        return False
    for left_key in _model_match_keys(left):
        if left_key == right_norm or left_key in right_norm or right_norm in left_key:
            return True
    return False


def find_conversation_subentry_for_model(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
) -> dict[str, Any] | None:
    for subentry in list_subentries(base_url, token, entry_id):
        if subentry.get("subentry_type") != "conversation":
            continue
        title = subentry.get("title") or ""
        if models_match(model, title):
            return subentry
        agent_id = resolve_agent_for_subentry(base_url, token, subentry["subentry_id"])
        if agent_id and models_match(model, agent_id):
            return subentry
    return None


def ensure_conversation_for_model(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
) -> tuple[str, str]:
    wait_for_config_entry_loaded(base_url, token, entry_id)
    matched = find_conversation_subentry_for_model(base_url, token, entry_id, model)
    created = False
    if matched:
        subentry_id = matched["subentry_id"]
    else:
        subentry_id = create_conversation_subentry(base_url, token, entry_id, model)
        created = True

    if not created:
        reconfigure_conversation_subentry(base_url, token, entry_id, subentry_id, model)
    agent_id = resolve_agent_for_subentry(base_url, token, subentry_id)
    if agent_id is None:
        raise RuntimeError(
            f"No conversation agent entity found for OpenRouter model {model!r}"
        )
    return subentry_id, agent_id


def create_conversation_subentry(
    base_url: str,
    token: str,
    entry_id: str,
    model: str,
) -> str:
    before = {
        subentry["subentry_id"]
        for subentry in list_subentries(base_url, token, entry_id)
        if subentry.get("subentry_type") == "conversation"
    }
    result = run_conversation_subentry_flow(
        base_url, token, entry_id, model, subentry_id=None
    )
    created = result.get("result") or {}
    subentry_id = created.get("subentry_id")
    if subentry_id:
        return subentry_id

    if result.get("type") != "create_entry":
        raise RuntimeError(f"Unexpected conversation subentry result: {result}")

    matched = find_conversation_subentry_for_model(base_url, token, entry_id, model)
    if matched:
        return matched["subentry_id"]

    after = [
        subentry
        for subentry in list_subentries(base_url, token, entry_id)
        if subentry.get("subentry_type") == "conversation"
        and subentry["subentry_id"] not in before
    ]
    if len(after) == 1:
        return after[0]["subentry_id"]
    raise RuntimeError(f"Could not resolve created conversation subentry: {result}")


def reconfigure_conversation_subentry(
    base_url: str,
    token: str,
    entry_id: str,
    subentry_id: str,
    model: str,
) -> None:
    result = run_conversation_subentry_flow(
        base_url, token, entry_id, model, subentry_id=subentry_id
    )
    if not _subentry_flow_succeeded(result):
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
    del preferred_subentry_id, dedupe
    return ensure_conversation_for_model(base_url, token, entry_id, model)
