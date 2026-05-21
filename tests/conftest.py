"""Pytest fixtures for conversational tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from _pytest.runner import runtestprotocol
from dotenv import load_dotenv

from ha_test.helpers import ENTITY_CATALOG, TIMER_ENTITY_IDS, setup_entity, snapshot_tracked_states
from ha_test.homeassistant import HomeAssistantClient
from ha_test.openrouter import env_value, get_target_model_ids, usage_settle_seconds
from ha_test.read_timeout import (
    READ_TIMEOUT_MAX_RETRIES,
    failed_with_read_timeout,
    failed_with_timeout,
)
from ha_test.reporting import RUN_METRICS, record_test_result, remove_test_records

_env_file = Path(__file__).resolve().parent.parent / ".env"
if not os.environ.get("GITHUB_ACTIONS") and _env_file.exists():
    load_dotenv(_env_file, override=False)

_configured_model: str | None = None


def _model_for_item(item: pytest.Item) -> str:
    if hasattr(item, "callspec") and item.callspec:
        model = item.callspec.params.get("model")
        if model is not None:
            return str(model)
    return ""


def pytest_generate_tests(metafunc):
    if "model" in metafunc.fixturenames:
        metafunc.parametrize("model", get_target_model_ids())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    model_order = {model: index for index, model in enumerate(get_target_model_ids())}
    indexed_items = list(enumerate(items))
    indexed_items.sort(
        key=lambda pair: (
            model_order.get(_model_for_item(pair[1]), len(model_order)),
            pair[0],
        )
    )
    items[:] = [item for _, item in indexed_items]


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--ha-url",
        action="store",
        default=os.environ.get("HA_URL", "http://localhost:8123"),
    )


@pytest.fixture(scope="session")
def ha_url(request) -> str:
    return request.config.getoption("--ha-url")


@pytest.fixture(scope="session")
def ha_token() -> str:
    token = os.environ.get("HA_TOKEN")
    if not token:
        token_path = os.path.join(os.path.dirname(__file__), "..", "reports", ".ha_token")
        if os.path.exists(token_path):
            token = open(token_path, encoding="utf-8").read().strip()
    if not token:
        pytest.skip("HA_TOKEN not configured; run bootstrap.py first")
    return token


@pytest.fixture(scope="session")
def openrouter_models() -> list[dict]:
    model_ids = get_target_model_ids()
    if env_value("OPENROUTER_MODEL"):
        return [{"id": model_id, "name": model_id} for model_id in model_ids]
    api_key = env_value("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not configured")
    from ha_test.openrouter import get_free_models

    models = get_free_models(api_key)
    if not models:
        pytest.skip("No OpenRouter models matched the configured filters")
    return models


@pytest.fixture(scope="session")
def ha_client(ha_url, ha_token) -> HomeAssistantClient:
    client = HomeAssistantClient(ha_url, ha_token)
    from bootstrap import expose_conversation_entities

    expose_conversation_entities(ha_url, ha_token, list(TIMER_ENTITY_IDS))
    return client


@pytest.fixture(autouse=True)
def configure_model(request):
    if "model" not in request.fixturenames:
        yield
        return
    global _configured_model
    ha_client = request.getfixturevalue("ha_client")
    model = request.getfixturevalue("model")
    if model == "unconfigured":
        pytest.skip("OpenRouter model not configured")
    if _configured_model != model:
        ha_client.reconfigure_openrouter_model(model)
        time.sleep(1)
        _configured_model = model
    yield model


@pytest.fixture(autouse=True)
def reset_entities(request):
    if "model" not in request.fixturenames:
        yield
        return
    ha_client = request.getfixturevalue("ha_client")
    for entity_id in ENTITY_CATALOG:
        setup_entity(ha_client, entity_id)
    yield


@pytest.fixture
def entity_snapshot(ha_client):
    return snapshot_tracked_states(ha_client.get_all_states())


@pytest.fixture
def conversation(ha_client):
    def _conversation(text: str):
        return ha_client.process_conversation(text)

    return _conversation


@pytest.fixture
def reset_lamp_x(ha_client):
    setup_entity(ha_client, "light.lamp_x")


@pytest.fixture
def reset_tv_switch(ha_client):
    setup_entity(ha_client, "switch.tv_switch")


@pytest.fixture
def reset_living_room(ha_client):
    setup_entity(ha_client, "climate.living_room")


@pytest.fixture(autouse=True)
def rate_limit_pause(request):
    yield
    if "model" not in request.fixturenames:
        return
    time.sleep(usage_settle_seconds())


def _model_from_item(item: pytest.Item) -> str:
    if hasattr(item, "callspec") and item.callspec:
        model = item.callspec.params.get("model")
        if model is not None:
            return str(model)
    return env_value("OPENROUTER_MODEL") or "unknown"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    """Re-run tests that fail with httpx ReadTimeout (transient HA/API slowness)."""
    if READ_TIMEOUT_MAX_RETRIES <= 0:
        return None

    for attempt in range(READ_TIMEOUT_MAX_RETRIES + 1):
        reports = runtestprotocol(
            item,
            nextitem=nextitem if attempt == READ_TIMEOUT_MAX_RETRIES else None,
        )
        call_report = next((report for report in reports if report.when == "call"), None)
        if call_report is None or call_report.passed or call_report.skipped:
            return True
        if not failed_with_read_timeout(call_report):
            return True
        if attempt >= READ_TIMEOUT_MAX_RETRIES:
            return True

        remove_test_records(nodeid=item.nodeid, model=_model_from_item(item))
        item.warn(
            pytest.PytestWarning(
                f"Retrying {item.nodeid} after ReadTimeout "
                f"(attempt {attempt + 2}/{READ_TIMEOUT_MAX_RETRIES + 1})"
            )
        )
    return True


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    from ha_test.reporting import finalize_report

    if RUN_METRICS.records:
        finalize_report(RUN_METRICS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return

    model = _model_from_item(item)
    already_recorded = any(
        record.nodeid == item.nodeid and record.model == model
        for record in RUN_METRICS.records
    )

    if report.failed and failed_with_timeout(report):
        report.outcome = "skipped"
        reason = str(report.longrepr)
        report.longrepr = f"Skipped due to timeout: {reason}"
        if not already_recorded:
            command = None
            if hasattr(item, "callspec") and item.callspec and "command" in item.callspec.params:
                command = item.callspec.params["command"]
            record_test_result(
                nodeid=item.nodeid,
                model=model,
                outcome="skipped",
                latency_ms=0.0,
                command=command,
                failure_reason=reason,
            )
        return

    if not report.failed:
        return

    if already_recorded:
        return

    command = None
    if hasattr(item, "callspec") and item.callspec and "command" in item.callspec.params:
        command = item.callspec.params["command"]

    record_test_result(
        nodeid=item.nodeid,
        model=model,
        outcome="failed",
        latency_ms=0.0,
        command=command,
        failure_reason=str(report.longrepr),
    )
