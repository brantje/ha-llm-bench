"""OpenRouter model discovery and activity API client."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ha_test.rate_limit import request_with_rate_limit_retry

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "reports" / "models_cache.json"
CACHE_TTL_SECONDS = int(os.environ.get("OPENROUTER_CACHE_TTL", "3600"))


def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None:
        return None
    value = value.strip().strip("'\"")
    return value or None


def get_target_model_ids(api_key: str | None = None) -> list[str]:
    model = env_value("OPENROUTER_MODEL")
    if model:
        return [model]
    api_key = api_key or env_value("OPENROUTER_API_KEY")
    if not api_key:
        return ["unconfigured"]
    models = get_free_models(api_key)
    return [item["id"] for item in models] or ["unconfigured"]


def _headers(api_key: str, management: bool = False) -> dict[str, str]:
    key = os.environ.get("OPENROUTER_MANAGEMENT_KEY") if management else api_key
    if not key:
        raise RuntimeError("OpenRouter API key is required")
    return {"Authorization": f"Bearer {key}"}


def get_models(api_key: str | None = None, use_cache: bool = True) -> list[dict[str, Any]]:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    if use_cache and CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text())
        if time.time() - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS:
            return cached["models"]

    response = request_with_rate_limit_retry(
        lambda: httpx.get(
            f"{OPENROUTER_BASE}/models",
            headers=_headers(api_key),
            timeout=30,
        )
    )
    response.raise_for_status()
    models = response.json()["data"]
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"fetched_at": time.time(), "models": models}, indent=2)
    )
    return models


def _is_free(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    prompt = pricing.get("prompt", "1")
    completion = pricing.get("completion", "1")
    return str(prompt) in {"0", "0.0", "0.00"} and str(completion) in {"0", "0.0", "0.00"}


def _supports_tools(model: dict[str, Any]) -> bool:
    return "tools" in (model.get("supported_parameters") or [])


def _has_text_output(model: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    outputs = architecture.get("output_modalities") or ["text"]
    return "text" in outputs


def filter_models(
    models: list[dict[str, Any]],
    *,
    free_only: bool = True,
    require_tools: bool = True,
    min_context: int = 8192,
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    max_models: int | None = None,
) -> list[dict[str, Any]]:
    allow = {item.strip() for item in (allowlist or []) if item.strip()}
    deny = {item.strip() for item in (denylist or []) if item.strip()}
    filtered: list[dict[str, Any]] = []

    for model in models:
        model_id = model["id"]
        if allow and model_id not in allow:
            continue
        if model_id in deny:
            continue
        if free_only and not _is_free(model):
            continue
        if require_tools and not _supports_tools(model):
            continue
        if not _has_text_output(model):
            continue
        context = model.get("context_length") or 0
        if context and context < min_context:
            continue
        filtered.append(model)

    filtered.sort(key=lambda item: item["id"])
    if max_models is not None:
        filtered = filtered[:max_models]
    return filtered


def get_free_models(api_key: str | None = None) -> list[dict[str, Any]]:
    free_only = os.environ.get("OPENROUTER_FREE_ONLY", "true").lower() != "false"
    min_context = int(os.environ.get("OPENROUTER_MIN_CONTEXT", "8192"))
    allowlist = [part for part in os.environ.get("OPENROUTER_ALLOWLIST", "").split(",") if part]
    denylist = [part for part in os.environ.get("OPENROUTER_DENYLIST", "").split(",") if part]
    max_models = os.environ.get("OPENROUTER_MAX_MODELS")
    models = get_models(api_key=api_key)
    return filter_models(
        models,
        free_only=free_only,
        require_tools=True,
        min_context=min_context,
        allowlist=allowlist or None,
        denylist=denylist or None,
        max_models=int(max_models) if max_models else None,
    )


def get_activity(date: str | None = None, management_key: str | None = None) -> list[dict[str, Any]]:
    key = management_key or os.environ.get("OPENROUTER_MANAGEMENT_KEY")
    if not key:
        return []
    params = {"date": date} if date else None
    response = request_with_rate_limit_retry(
        lambda: httpx.get(
            f"{OPENROUTER_BASE}/activity",
            headers=_headers(key, management=True),
            params=params,
            timeout=30,
        )
    )
    if response.status_code >= 400:
        return []
    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    if isinstance(payload, list):
        return payload
    return []


def aggregate_activity_for_models(
    activity: list[dict[str, Any]],
    model_ids: set[str],
) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    for item in activity:
        endpoint = item.get("endpoint_id") or item.get("model") or item.get("model_permaslug")
        if endpoint not in model_ids:
            continue
        bucket = totals.setdefault(
            endpoint,
            {
                "cost_usd": 0.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
                "total_tokens": 0.0,
            },
        )
        bucket["cost_usd"] += float(
            item.get("usage")
            or item.get("cost")
            or item.get("byok_usage_inference")
            or 0.0
        )
        bucket["prompt_tokens"] += float(item.get("tokens_prompt") or item.get("prompt_tokens") or 0)
        bucket["completion_tokens"] += float(
            item.get("tokens_completion") or item.get("completion_tokens") or 0
        )
        bucket["total_tokens"] = bucket["prompt_tokens"] + bucket["completion_tokens"]
    return totals
