#!/usr/bin/env python3
"""Bootstrap Home Assistant for conversational testing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import websockets
from dotenv import dotenv_values, load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
ENV_PATH = PROJECT_ROOT / ".env"
REPORTS_DIR = PROJECT_ROOT / "reports"
TOKEN_PATH = REPORTS_DIR / ".ha_token"
BASELINE_PATH = REPORTS_DIR / "baseline_states.json"

HA_URL = os.environ.get("HA_URL", "http://localhost:8123")
USERNAME = "admin"
PASSWORD = "admin"
STARTUP_TIMEOUT = 180
from ha_test.openrouter_setup import (
    configure_openrouter_conversation,
    find_openrouter_entry,
    get_config_entries,
)


def load_env() -> dict[str, str]:
    values = dotenv_values(ENV_PATH)
    return {k: v for k, v in values.items() if v is not None}


def save_env_value(key: str, value: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("")
    set_key(str(ENV_PATH), key, value)


def wait_for_ha(base_url: str, timeout: int = STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/", timeout=5)
            if response.status_code in (200, 401, 403):
                return
        except httpx.RequestError as exc:
            last_error = exc
        time.sleep(2)
    raise TimeoutError(
        f"Home Assistant did not become ready within {timeout}s: {last_error}"
    )


def needs_onboarding(base_url: str) -> bool:
    response = httpx.get(f"{base_url}/api/onboarding", timeout=10)
    if response.status_code != 200:
        return False
    steps = response.json()
    return any(not step.get("done", False) for step in steps)


def perform_onboarding(base_url: str) -> str:
    client_id = f"{base_url}/"
    response = httpx.post(
        f"{base_url}/api/onboarding/users",
        json={
            "client_id": client_id,
            "name": "Admin",
            "username": USERNAME,
            "password": PASSWORD,
            "language": "en",
        },
        timeout=30,
    )
    response.raise_for_status()
    auth_code = response.json()["auth_code"]

    token_response = httpx.post(
        f"{base_url}/auth/token",
        content=urlencode(
            {
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": auth_code,
            }
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    token_response.raise_for_status()
    short_lived_token = token_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {short_lived_token}"}

    for step in ("core_config", "analytics"):
        httpx.post(
            f"{base_url}/api/onboarding/{step}",
            json={"client_id": client_id},
            headers=headers,
            timeout=30,
        )

    httpx.post(
        f"{base_url}/api/onboarding/integration",
        json={"client_id": client_id, "redirect_uri": client_id},
        headers=headers,
        timeout=30,
    )
    return mint_long_lived_token(base_url, short_lived_token)


def password_login(base_url: str) -> str:
    client_id = f"{base_url}/"
    flow_response = httpx.post(
        f"{base_url}/auth/login_flow",
        json={
            "client_id": client_id,
            "handler": ["homeassistant", None],
            "redirect_uri": client_id,
        },
        timeout=15,
    )
    flow_response.raise_for_status()
    flow_id = flow_response.json()["flow_id"]

    cred_response = httpx.post(
        f"{base_url}/auth/login_flow/{flow_id}",
        json={
            "client_id": client_id,
            "username": USERNAME,
            "password": PASSWORD,
        },
        timeout=15,
    )
    cred_response.raise_for_status()
    auth_code = cred_response.json()["result"]

    token_response = httpx.post(
        f"{base_url}/auth/token",
        content=urlencode(
            {
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": auth_code,
            }
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    token_response.raise_for_status()
    short_lived_token = token_response.json()["access_token"]
    return mint_long_lived_token(base_url, short_lived_token)


async def _ws_request(base_url: str, access_token: str, command: dict) -> dict:
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


def mint_long_lived_token(base_url: str, short_lived_token: str) -> str:
    result = asyncio.run(
        _ws_request(
            base_url,
            short_lived_token,
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": "ha-test-harness",
                "lifespan": 3650,
            },
        )
    )
    if not result.get("success"):
        raise RuntimeError(f"Failed to create long-lived token: {result}")
    return result["result"]


def api_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    **kwargs,
) -> httpx.Response:
    if not path.startswith("/api/"):
        path = f"/api/{path.lstrip('/')}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Content-Type", "application/json")
    return httpx.request(method, f"{base_url}{path}", headers=headers, timeout=60, **kwargs)


def start_config_flow(base_url: str, token: str, handler: str | list[str]) -> dict:
    response = api_request(
        base_url,
        token,
        "POST",
        "/api/config/config_entries/flow",
        json={"handler": handler},
    )
    response.raise_for_status()
    return response.json()


def submit_config_flow(base_url: str, token: str, flow_id: str, data: dict) -> dict:
    response = api_request(
        base_url,
        token,
        "POST",
        f"/api/config/config_entries/flow/{flow_id}",
        json=data,
    )
    response.raise_for_status()
    return response.json()


def start_subentry_flow(
    base_url: str,
    token: str,
    entry_id: str,
    subentry_type: str,
    subentry_id: str | None = None,
) -> dict:
    payload: dict = {"handler": [entry_id, subentry_type]}
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


def submit_subentry_flow(base_url: str, token: str, flow_id: str, data: dict) -> dict:
    response = api_request(
        base_url,
        token,
        "POST",
        f"/api/config/config_entries/subentries/flow/{flow_id}",
        json=data,
    )
    response.raise_for_status()
    return response.json()


def configure_openrouter(base_url: str, token: str, api_key: str, model: str) -> dict:
    entries = get_config_entries(base_url, token)
    entry = find_openrouter_entry(entries)
    if entry is None:
        flow = start_config_flow(base_url, token, "open_router")
        result = submit_config_flow(base_url, token, flow["flow_id"], {"api_key": api_key})
        if result.get("type") != "create_entry":
            raise RuntimeError(f"Unexpected OpenRouter setup result: {result}")
        entry_id = result["result"]["entry_id"]
    else:
        entry_id = entry["entry_id"]

    time.sleep(2)
    subentry_id, agent_id = configure_openrouter_conversation(
        base_url,
        token,
        entry_id,
        model,
    )

    entries = get_config_entries(base_url, token)
    entry = next(item for item in entries if item["entry_id"] == entry_id)
    entry["_conversation_subentry_id"] = subentry_id
    entry["_conversation_agent_id"] = agent_id
    return entry


def snapshot_baseline_states(base_url: str, token: str) -> None:
    response = api_request(base_url, token, "GET", "/api/states")
    response.raise_for_status()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tracked = {
        state["entity_id"]: state
        for state in response.json()
        if state["entity_id"].startswith(
            ("light.", "switch.", "climate.", "input_", "scene.", "script.")
        )
    }
    BASELINE_PATH.write_text(json.dumps(tracked, indent=2))


def print_recent_history(*, limit: int = 5) -> None:
    from ha_test.reporting import load_history_index, format_history_summary

    index = load_history_index()
    if not index:
        return
    print(f"Recent benchmark runs ({len(index)} archived):")
    for entry in index[:limit]:
        print(f"  - {format_history_summary(entry)}")
    print("  Results viewer: python3 -m http.server 8080  ->  http://localhost:8080/docs/")
    print("  List history:   PYTHONPATH=src .venv/bin/python -m ha_test.history list")
    print("")


def resolve_default_model(env: dict[str, str]) -> str:
    from ha_test.openrouter import get_target_model_ids

    models = get_target_model_ids(env.get("OPENROUTER_API_KEY"))
    if not models or models == ["unconfigured"]:
        raise RuntimeError("No OpenRouter models matched the configured filters")
    return models[0]


def token_is_valid(base_url: str, token: str) -> bool:
    response = httpx.get(
        f"{base_url}/api/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return response.status_code == 200


def load_existing_token() -> str | None:
    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    env = load_env()
    token = env.get("HA_TOKEN")
    return token or None


def obtain_token(base_url: str) -> str:
    existing = load_existing_token()
    if existing and token_is_valid(base_url, existing):
        return existing
    if needs_onboarding(base_url):
        return perform_onboarding(base_url)
    return password_login(base_url)


def bootstrap(base_url: str, reset: bool = False) -> None:
    if reset and (PROJECT_ROOT / "docker" / ".storage").exists():
        import shutil

        shutil.rmtree(PROJECT_ROOT / "docker" / ".storage")

    wait_for_ha(base_url)
    token = obtain_token(base_url)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token)
    save_env_value("HA_TOKEN", token)
    save_env_value("HA_URL", base_url)

    env = load_env()
    api_key = env.get("OPENROUTER_API_KEY")
    if api_key:
        from ha_test.test_plan import print_test_plan

        print("Test plan preview:")
        print_test_plan(api_key)
        print("")
        print_recent_history()
        model = resolve_default_model(env)
        entry = configure_openrouter(base_url, token, api_key, model)
        subentry_id = entry["_conversation_subentry_id"]
        agent_id = entry["_conversation_agent_id"]
        save_env_value("HA_CONVERSATION_AGENT_ID", agent_id)
        print(f"Configured OpenRouter model: {model}")
        print(f"Conversation subentry: {subentry_id}")
        print(f"Conversation agent: {agent_id}")
        from ha_test.openrouter_setup import models_match

        if not models_match(model, agent_id):
            print(
                "Note: the agent entity name/title may still reflect an older model; "
                "the configured model above is what OpenRouter will use."
            )
    else:
        print("OPENROUTER_API_KEY not set; skipping OpenRouter configuration")

    snapshot_baseline_states(base_url, token)
    print(f"Bootstrap complete. Token saved to {TOKEN_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Home Assistant test harness")
    parser.add_argument("--reset", action="store_true", help="Remove .storage before bootstrapping")
    parser.add_argument("--url", default=HA_URL, help="Home Assistant base URL")
    parser.add_argument(
        "--history",
        action="store_true",
        help="List archived benchmark runs and exit",
    )
    args = parser.parse_args()
    load_dotenv(ENV_PATH, override=True)
    if args.history:
        from ha_test.history import print_history_list

        raise SystemExit(print_history_list())
    bootstrap(args.url, reset=args.reset)


if __name__ == "__main__":
    main()
