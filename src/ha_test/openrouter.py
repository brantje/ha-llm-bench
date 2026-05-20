"""OpenRouter model discovery and activity API client."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ha_test.rate_limit import request_with_rate_limit_retry

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "reports" / "models_cache.json"
CACHE_TTL_SECONDS = int(os.environ.get("OPENROUTER_CACHE_TTL", "3600"))
DEFAULT_USAGE_SETTLE_SECONDS = 12.0


def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None:
        return None
    value = value.strip().strip("'\"")
    return value or None


def usage_settle_seconds() -> float:
    return float(os.environ.get("OPENROUTER_USAGE_SETTLE_SECONDS", DEFAULT_USAGE_SETTLE_SECONDS))


def parse_csv_ids(value: str) -> list[str]:
    return [
        part.strip().strip("'\"")
        for part in value.split(",")
        if part.strip().strip("'\"")
    ]


def get_target_model_ids(api_key: str | None = None) -> list[str]:
    model = env_value("OPENROUTER_MODEL")
    if model:
        return parse_csv_ids(model)
    api_key = api_key or env_value("OPENROUTER_API_KEY")
    if not api_key:
        return ["unconfigured"]
    models = get_free_models(api_key)
    return [item["id"] for item in models] or ["unconfigured"]


def _headers(api_key: str, management: bool = False) -> dict[str, str]:
    key = env_value("OPENROUTER_MANAGEMENT_KEY") if management else api_key
    if not key:
        raise RuntimeError("OpenRouter API key is required")
    return {"Authorization": f"Bearer {key}"}


def get_api_key_usage(api_key: str | None = None) -> float | None:
    balance = get_api_key_credit_balance(api_key)
    return balance.get("total_usage")


def get_api_key_credit_balance(api_key: str | None = None) -> dict[str, float | None]:
    key = api_key or env_value("OPENROUTER_API_KEY")
    if not key:
        return {"total_credits": None, "total_usage": None, "remaining": None}

    response = request_with_rate_limit_retry(
        lambda: httpx.get(
            f"{OPENROUTER_BASE}/credits",
            headers=_headers(key),
            timeout=30,
        )
    )
    if response.status_code >= 400:
        return {"total_credits": None, "total_usage": None, "remaining": None}

    payload = response.json().get("data") or {}
    total_credits = payload.get("total_credits")
    total_usage = payload.get("total_usage")
    credits = float(total_credits) if total_credits is not None else None
    usage = float(total_usage) if total_usage is not None else None
    remaining = (credits - usage) if credits is not None and usage is not None else None
    return {
        "total_credits": credits,
        "total_usage": usage,
        "remaining": remaining,
    }


def get_model_pricing_lookup(api_key: str | None = None) -> dict[str, dict[str, str]]:
    return {model["id"]: model.get("pricing") or {} for model in get_models(api_key=api_key)}


def _model_pricing_lookup(api_key: str | None = None) -> dict[str, dict[str, str]]:
    return get_model_pricing_lookup(api_key=api_key)


def estimate_tokens_from_cost(model_id: str, cost_usd: float) -> dict[str, float]:
    if cost_usd <= 0:
        return {"prompt_tokens": 0.0, "completion_tokens": 0.0, "total_tokens": 0.0}

    pricing = _model_pricing_lookup().get(model_id) or {}
    prompt_rate = float(pricing.get("prompt") or 0)
    completion_rate = float(pricing.get("completion") or 0)
    if prompt_rate <= 0 and completion_rate <= 0:
        return {"prompt_tokens": 0.0, "completion_tokens": 0.0, "total_tokens": 0.0}

    blended_rate = (0.9 * prompt_rate) + (0.1 * completion_rate)
    total_tokens = cost_usd / blended_rate if blended_rate > 0 else 0.0
    prompt_tokens = total_tokens * 0.9
    completion_tokens = total_tokens * 0.1
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def estimate_tokens_from_activity_history(
    activity: dict[str, float],
    num_requests: int,
) -> dict[str, float]:
    requests = float(activity.get("requests") or 0)
    if requests <= 0 or num_requests <= 0:
        return {"prompt_tokens": 0.0, "completion_tokens": 0.0, "total_tokens": 0.0}

    prompt_tokens = float(activity.get("prompt_tokens") or 0) / requests * num_requests
    completion_tokens = float(activity.get("completion_tokens") or 0) / requests * num_requests
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def match_activity_item_to_model(
    item: dict[str, Any],
    model_ids: set[str],
) -> str | None:
    candidates = [
        item.get("model"),
        item.get("model_permaslug"),
        item.get("endpoint_id"),
    ]
    for candidate in candidates:
        if candidate in model_ids:
            return candidate

    model_slug = item.get("model")
    permaslug = item.get("model_permaslug")
    for model_id in model_ids:
        if model_id in candidates:
            return model_id
        if model_slug and (model_id == model_slug or model_id.startswith(f"{model_slug}-")):
            return model_id
        if permaslug and model_id == permaslug:
            return model_id
    return None


def get_models(
    api_key: str | None = None,
    use_cache: bool = True,
    output_modalities: str = "text",
) -> list[dict[str, Any]]:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    if use_cache and CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text())
        if (
            time.time() - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS
            and cached.get("output_modalities") == output_modalities
        ):
            return cached["models"]

    response = request_with_rate_limit_retry(
        lambda: httpx.get(
            f"{OPENROUTER_BASE}/models",
            headers=_headers(api_key),
            params={"output_modalities": output_modalities},
            timeout=30,
        )
    )
    response.raise_for_status()
    models = response.json()["data"]
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "output_modalities": output_modalities,
                "models": models,
            },
            indent=2,
        )
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
    outputs = architecture.get("output_modalities")
    return bool(outputs and "text" in outputs)


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

    if max_models is not None:
        filtered = filtered[:max_models]
    return filtered


def parse_bool_env(key: str, *, default: bool = True) -> bool:
    value = env_value(key)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no", "off"}


def get_free_models(api_key: str | None = None) -> list[dict[str, Any]]:
    free_only = parse_bool_env("OPENROUTER_FREE_ONLY", default=True)
    min_context = int(env_value("OPENROUTER_MIN_CONTEXT") or "8192")
    allowlist = parse_csv_ids(os.environ.get("OPENROUTER_ALLOWLIST", ""))
    denylist = parse_csv_ids(os.environ.get("OPENROUTER_DENYLIST", ""))
    max_models = env_value("OPENROUTER_MAX_MODELS")
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
    key = management_key or env_value("OPENROUTER_MANAGEMENT_KEY")
    if not key:
        return []

    params: dict[str, str] | None = None
    if date:
        today_utc = datetime.now(UTC).date()
        requested = datetime.strptime(date, "%Y-%m-%d").date()
        if requested < today_utc:
            params = {"date": date}

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


def get_activity_totals_for_models(model_ids: set[str]) -> dict[str, dict[str, float]]:
    activity = get_activity()
    return aggregate_activity_for_models(activity, model_ids)


def get_model_activity_totals(model_id: str) -> dict[str, float]:
    return get_activity_totals_for_models({model_id}).get(
        model_id,
        {
            "cost_usd": 0.0,
            "prompt_tokens": 0.0,
            "completion_tokens": 0.0,
            "total_tokens": 0.0,
            "requests": 0.0,
        },
    )


def activity_tokens_delta(
    before: dict[str, float],
    after: dict[str, float],
) -> dict[str, float]:
    prompt_tokens = max(0.0, after.get("prompt_tokens", 0.0) - before.get("prompt_tokens", 0.0))
    completion_tokens = max(
        0.0,
        after.get("completion_tokens", 0.0) - before.get("completion_tokens", 0.0),
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "requests": max(0.0, after.get("requests", 0.0) - before.get("requests", 0.0)),
    }


def aggregate_activity_for_models(
    activity: list[dict[str, Any]],
    model_ids: set[str],
) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    for item in activity:
        model_id = match_activity_item_to_model(item, model_ids)
        if model_id is None:
            continue
        bucket = totals.setdefault(
            model_id,
            {
                "cost_usd": 0.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
                "total_tokens": 0.0,
                "requests": 0.0,
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
        bucket["requests"] += float(item.get("requests") or 0)
        bucket["total_tokens"] = bucket["prompt_tokens"] + bucket["completion_tokens"]
    return totals
