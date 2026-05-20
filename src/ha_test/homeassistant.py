"""Home Assistant REST API wrapper."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
import websockets

from ha_test.rate_limit import (
    should_retry_after_conversation_error,
    wait_for_openrouter_rate_limit,
)

from ha_test.openrouter import (
    env_value,
    activity_tokens_delta,
    estimate_tokens_from_cost,
    get_api_key_usage,
    get_model_activity_totals,
    parse_csv_ids,
    usage_settle_seconds,
)
from ha_test.openrouter_setup import (
    ensure_conversation_for_model,
    find_openrouter_entry,
    resolve_agent_for_subentry,
)

@dataclass
class ConversationResult:
    text: str
    response: dict[str, Any]
    latency_ms: float
    response_type: str | None = None
    speech: str | None = None
    cost_usd: float | None = None
    prompt_tokens: float | None = None
    completion_tokens: float | None = None
    total_tokens: float | None = None


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, agent_id: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.agent_id = agent_id
        self._entry_id: str | None = None
        self._conversation_subentry_id: str | None = None
        self._active_model_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not path.startswith("/api/"):
            path = f"/api/{path.lstrip('/')}"
        return httpx.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=kwargs.pop("timeout", 90),
            **kwargs,
        )

    def _resolve_model_id(self) -> str | None:
        model_id = self._active_model_id or env_value("OPENROUTER_MODEL")
        if not model_id:
            return None
        if "," in model_id:
            parsed = parse_csv_ids(model_id)
            return parsed[0] if parsed else model_id
        return model_id

    def _poll_activity_token_delta(
        self,
        model_id: str,
        activity_before: dict[str, float],
    ) -> dict[str, float] | None:
        settle_seconds = usage_settle_seconds()
        deadline = time.monotonic() + settle_seconds
        while time.monotonic() < deadline:
            activity_after = get_model_activity_totals(model_id)
            delta = activity_tokens_delta(activity_before, activity_after)
            if delta["requests"] > 0 or delta["total_tokens"] > 0:
                return delta
            time.sleep(0.5)

        activity_after = get_model_activity_totals(model_id)
        delta = activity_tokens_delta(activity_before, activity_after)
        if delta["requests"] > 0 or delta["total_tokens"] > 0:
            return delta
        return None

    def process_conversation(
        self,
        text: str,
        agent_id: str | None = None,
        language: str = "en",
        retries: int | None = None,
    ) -> ConversationResult:
        max_retries = retries
        if max_retries is None:
            max_retries = int(os.environ.get("OPENROUTER_RATE_LIMIT_MAX_RETRIES", "8"))

        api_key = os.environ.get("OPENROUTER_API_KEY")
        last_result: ConversationResult | None = None
        for attempt in range(max_retries):
            payload: dict[str, Any] = {"text": text, "language": language}
            selected_agent = agent_id or self.agent_id
            if selected_agent:
                payload["agent_id"] = selected_agent

            usage_before = get_api_key_usage(api_key)
            model_id = self._resolve_model_id()
            activity_before = None
            if model_id and env_value("OPENROUTER_MANAGEMENT_KEY"):
                activity_before = get_model_activity_totals(model_id)

            start = time.perf_counter()
            response = self._request("POST", "/api/conversation/process", json=payload)
            latency_ms = (time.perf_counter() - start) * 1000
            response.raise_for_status()
            body = response.json()
            usage_after = usage_before
            if usage_before is not None:
                settle_seconds = usage_settle_seconds()
                deadline = time.monotonic() + settle_seconds
                while time.monotonic() < deadline:
                    current_usage = get_api_key_usage(api_key)
                    if current_usage is not None and current_usage > usage_before:
                        usage_after = current_usage
                        break
                    time.sleep(0.5)
                else:
                    usage_after = get_api_key_usage(api_key)
            cost_usd = None
            if usage_before is not None and usage_after is not None:
                cost_usd = max(0.0, usage_after - usage_before)

            response_obj = body.get("response") or {}
            speech = None
            if response_obj.get("speech"):
                speech = response_obj["speech"].get("plain", {}).get("speech")

            prompt_tokens = None
            completion_tokens = None
            total_tokens = None
            if cost_usd is not None and cost_usd > 0 and model_id:
                estimated = estimate_tokens_from_cost(model_id, cost_usd)
                prompt_tokens = estimated["prompt_tokens"]
                completion_tokens = estimated["completion_tokens"]
                total_tokens = estimated["total_tokens"]
            elif activity_before is not None and model_id:
                token_delta = self._poll_activity_token_delta(model_id, activity_before)
                if token_delta:
                    prompt_tokens = token_delta["prompt_tokens"]
                    completion_tokens = token_delta["completion_tokens"]
                    total_tokens = token_delta["total_tokens"]

            last_result = ConversationResult(
                text=text,
                response=body,
                latency_ms=latency_ms,
                response_type=response_obj.get("response_type"),
                speech=speech,
                cost_usd=cost_usd,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            if last_result.response_type != "error":
                return last_result

            if attempt + 1 >= max_retries:
                break

            if not should_retry_after_conversation_error(
                response_type=last_result.response_type,
                speech=last_result.speech,
                response_body=body,
                api_key=api_key,
            ):
                return last_result

            wait_for_openrouter_rate_limit(api_key)

        assert last_result is not None
        return last_result

    def get_state(self, entity_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/api/states/{entity_id}")
        response.raise_for_status()
        return response.json()

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        response = self._request("GET", "/api/states")
        response.raise_for_status()
        return {state["entity_id"]: state for state in response.json()}

    def call_service(self, domain: str, service: str, data: dict[str, Any] | None = None) -> None:
        response = self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            json=data or {},
        )
        response.raise_for_status()

    def set_helper_state(self, entity_id: str, value: Any) -> None:
        domain = entity_id.split(".", 1)[0]
        if domain == "input_boolean":
            service = "turn_on" if value else "turn_off"
            self.call_service(domain, service, {"entity_id": entity_id})
            return
        if domain == "input_number":
            self.call_service(domain, "set_value", {"entity_id": entity_id, "value": value})
            return
        if domain == "input_select":
            self.call_service(domain, "select_option", {"entity_id": entity_id, "option": value})
            return
        raise ValueError(f"Unsupported helper entity: {entity_id}")

    def wait_for_state(
        self,
        entity_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float = 15.0,
        interval: float = 0.5,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_state = self.get_state(entity_id)
        while time.monotonic() < deadline:
            last_state = self.get_state(entity_id)
            if predicate(last_state):
                return last_state
            time.sleep(interval)
        raise TimeoutError(
            f"Timed out waiting for {entity_id}. Last state: {last_state}"
        )

    def get_config_entries(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/config/config_entries/entry")
        response.raise_for_status()
        return response.json()

    def _ws_call(self, command: dict[str, Any]) -> dict[str, Any]:
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/websocket"

        async def _run() -> dict[str, Any]:
            async with websockets.connect(ws_url, open_timeout=15) as websocket:
                await websocket.recv()
                await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth_result = json.loads(await websocket.recv())
                if auth_result.get("type") != "auth_ok":
                    raise RuntimeError(f"WebSocket auth failed: {auth_result}")
                await websocket.send(json.dumps(command))
                result = json.loads(await websocket.recv())
                if not result.get("success", True) and result.get("type") == "result":
                    raise RuntimeError(f"WebSocket command failed: {result}")
                if result.get("error"):
                    raise RuntimeError(f"WebSocket command failed: {result}")
                return result

        return asyncio.run(_run())

    def list_openrouter_subentries(self) -> list[dict[str, Any]]:
        for entry in self.get_config_entries():
            if entry.get("domain") != "open_router":
                continue
            result = self._ws_call(
                {
                    "id": 1,
                    "type": "config_entries/subentries/list",
                    "entry_id": entry["entry_id"],
                }
            )
            return result.get("result", [])
        return []

    def _lookup_subentry_for_agent(self, agent_id: str) -> str | None:
        for entry in list_entity_registry(self.base_url, self.token):
            if entry.get("entity_id") == agent_id:
                return entry.get("config_subentry_id")
        return None

    def reconfigure_openrouter_model(self, model_id: str) -> None:
        entry = find_openrouter_entry(self.get_config_entries())
        if entry is None:
            raise RuntimeError("OpenRouter config entry not found")
        subentry_id, agent_id = ensure_conversation_for_model(
            self.base_url,
            self.token,
            entry["entry_id"],
            model_id,
        )
        self._entry_id = entry["entry_id"]
        self._conversation_subentry_id = subentry_id
        self.agent_id = agent_id
        self._active_model_id = model_id

    def get_conversation_agent_id(self) -> str:
        if self._conversation_subentry_id:
            agent_id = resolve_agent_for_subentry(
                self.base_url,
                self.token,
                self._conversation_subentry_id,
            )
            if agent_id:
                self.agent_id = agent_id
                return agent_id

        if self.agent_id and self.agent_id != "conversation.home_assistant":
            subentry_id = self._lookup_subentry_for_agent(self.agent_id)
            if subentry_id:
                self._conversation_subentry_id = subentry_id
            return self.agent_id

        env_agent = env_value("HA_CONVERSATION_AGENT_ID")
        if env_agent and env_agent != "conversation.home_assistant":
            subentry_id = self._lookup_subentry_for_agent(env_agent)
            if subentry_id:
                self._conversation_subentry_id = subentry_id
            self.agent_id = env_agent
            return env_agent

        agents = [
            entity_id
            for entity_id in self.get_all_states()
            if entity_id.startswith("conversation.")
        ]
        openrouter_agents = [
            entity_id for entity_id in agents if entity_id != "conversation.home_assistant"
        ]
        if openrouter_agents:
            self.agent_id = openrouter_agents[0]
            subentry_id = self._lookup_subentry_for_agent(self.agent_id)
            if subentry_id:
                self._conversation_subentry_id = subentry_id
            return self.agent_id
        if agents:
            self.agent_id = agents[0]
            return self.agent_id
        raise RuntimeError("Conversation agent entity not found")
