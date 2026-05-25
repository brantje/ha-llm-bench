"""Shared helpers, entity catalog, and assertion utilities."""

from __future__ import annotations

import time
from typing import Any, Callable

TRACKED_PREFIXES = (
    "light.",
    "switch.",
    "climate.",
    "media_player.",
    "timer.",
    "input_",
    "scene.",
    "script.",
)

TIMER_ENTITY_IDS = (
    "timer.kitchen",
    "timer.upstairs",
    "timer.pizza",
    "timer.laundry",
)

ENTITY_CATALOG = {
    "light.lamp_x": {
        "friendly_name": "Lamp X",
        "domain": "light",
        "related_entities": (
            "input_boolean.lamp_x_power",
            "input_number.lamp_x_brightness",
        ),
        "setup": lambda client: (
            client.set_helper_state("input_boolean.lamp_x_power", True),
            client.set_helper_state("input_number.lamp_x_brightness", 255),
        ),
    },
    "switch.tv_switch": {
        "friendly_name": "TV Switch",
        "domain": "switch",
        "related_entities": ("input_boolean.tv_switch",),
        "setup": lambda client: client.set_helper_state("input_boolean.tv_switch", False),
    },
    "climate.living_room": {
        "friendly_name": "Living Room",
        "domain": "climate",
        "related_entities": (
            "input_number.living_room_temp",
            "input_select.living_room_hvac",
            "input_boolean.living_room_heater",
        ),
        "setup": lambda client: (
            client.set_helper_state("input_number.living_room_temp", 21),
            client.set_helper_state("input_select.living_room_hvac", "heat"),
            client.call_service(
                "climate",
                "set_temperature",
                {"entity_id": "climate.living_room", "temperature": 21},
            ),
        ),
    },
    "media_player.living_room": {
        "friendly_name": "Living Room Speaker",
        "domain": "media_player",
        "related_entities": (),
        "setup": lambda client: (
            client.call_service(
                "media_player",
                "media_stop",
                {"entity_id": "media_player.living_room"},
            ),
            client.call_service(
                "media_player",
                "volume_mute",
                {
                    "entity_id": "media_player.living_room",
                    "is_volume_muted": False,
                },
            ),
            client.call_service(
                "media_player",
                "volume_set",
                {
                    "entity_id": "media_player.living_room",
                    "volume_level": 0.5,
                },
            ),
        ),
    },
    "timer.kitchen": {
        "friendly_name": "Kitchen Timer",
        "domain": "timer",
        "related_entities": (),
        "setup": lambda client: client.call_service(
            "timer", "cancel", {"entity_id": "timer.kitchen"}
        ),
    },
    "timer.upstairs": {
        "friendly_name": "Upstairs Timer",
        "domain": "timer",
        "related_entities": (),
        "setup": lambda client: client.call_service(
            "timer", "cancel", {"entity_id": "timer.upstairs"}
        ),
    },
    "timer.pizza": {
        "friendly_name": "Pizza Timer",
        "domain": "timer",
        "related_entities": (),
        "setup": lambda client: client.call_service(
            "timer", "cancel", {"entity_id": "timer.pizza"}
        ),
    },
    "timer.laundry": {
        "friendly_name": "Laundry Timer",
        "domain": "timer",
        "related_entities": (),
        "setup": lambda client: client.call_service(
            "timer", "cancel", {"entity_id": "timer.laundry"}
        ),
    },
}


def allowed_entities_for(*entity_ids: str) -> set[str]:
    """Entities that may change during a test without counting as hallucination."""
    if not entity_ids:
        return set()

    allowed: set[str] = set(entity_ids)
    for entity_id in entity_ids:
        entry = ENTITY_CATALOG.get(entity_id)
        if entry:
            allowed.update(entry.get("related_entities", ()))

    for catalog_id, entry in ENTITY_CATALOG.items():
        related = entry.get("related_entities", ())
        if any(entity_id in related for entity_id in entity_ids):
            allowed.add(catalog_id)
            allowed.update(related)

    return allowed


def setup_entity(client, entity_id: str) -> None:
    catalog = ENTITY_CATALOG[entity_id]
    result = catalog["setup"](client)
    if isinstance(result, tuple):
        for action in result:
            action


def snapshot_tracked_states(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        entity_id: state
        for entity_id, state in states.items()
        if entity_id.startswith(TRACKED_PREFIXES)
    }


def get_changed_entities(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[str]:
    changed = []
    for entity_id, old_state in before.items():
        new_state = after.get(entity_id)
        if new_state is None:
            continue
        if old_state.get("state") != new_state.get("state"):
            changed.append(entity_id)
    return changed


def assert_no_state_changes(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> None:
    changed = get_changed_entities(before, after)
    if changed:
        details = []
        for entity_id in changed:
            old = before[entity_id].get("state")
            new = after[entity_id].get("state")
            details.append(f"{entity_id}: {old!r} -> {new!r}")
        raise AssertionError(f"Unexpected state changes: {'; '.join(details)}")


def assert_light_off(state: dict[str, Any]) -> None:
    assert state["state"] == "off", f"Expected light off, got {state['state']}"


def assert_light_on(state: dict[str, Any]) -> None:
    assert state["state"] == "on", f"Expected light on, got {state['state']}"


def assert_switch_on(state: dict[str, Any]) -> None:
    assert state["state"] == "on", f"Expected switch on, got {state['state']}"


def assert_switch_off(state: dict[str, Any]) -> None:
    assert state["state"] == "off", f"Expected switch off, got {state['state']}"


def assert_climate_temp(state: dict[str, Any], expected: float, tolerance: float = 0.6) -> None:
    actual = float(state["attributes"].get("temperature", state["state"]))
    assert abs(actual - expected) <= tolerance, f"Expected {expected}, got {actual}"


def timer_remaining_seconds(state: dict[str, Any]) -> int:
    remaining = (state.get("attributes") or {}).get("remaining", 0)
    if isinstance(remaining, (int, float)):
        return int(remaining)
    if isinstance(remaining, str) and ":" in remaining:
        hours, minutes, seconds = (int(part) for part in remaining.split(":"))
        return hours * 3600 + minutes * 60 + seconds
    return 0


def assert_timer_active(state: dict[str, Any], *, min_remaining: int = 1) -> None:
    assert state["state"] == "active", f"Expected timer active, got {state['state']}"
    remaining = timer_remaining_seconds(state)
    assert remaining >= min_remaining, f"Expected remaining >= {min_remaining}, got {remaining}"


def cancel_all_timers(client, entity_ids: tuple[str, ...] = TIMER_ENTITY_IDS) -> None:
    for entity_id in entity_ids:
        client.call_service("timer", "cancel", {"entity_id": entity_id})


def active_timers(client, entity_ids: tuple[str, ...] = TIMER_ENTITY_IDS) -> list[str]:
    return [
        entity_id
        for entity_id in entity_ids
        if client.get_state(entity_id)["state"] == "active"
    ]


def wait_for_active_timer_count(
    client,
    *,
    exact: int | None = None,
    minimum: int | None = None,
    entity_ids: tuple[str, ...] = TIMER_ENTITY_IDS,
    timeout: float = 25.0,
    interval: float = 0.5,
) -> list[str]:
    deadline = time.monotonic() + timeout
    last_active: list[str] = []
    while time.monotonic() < deadline:
        last_active = active_timers(client, entity_ids)
        if exact is not None and len(last_active) == exact:
            return last_active
        if minimum is not None and len(last_active) >= minimum:
            return last_active
        time.sleep(interval)
    raise TimeoutError(
        f"Timed out waiting for timer count "
        f"(exact={exact}, minimum={minimum}). Last active: {last_active}"
    )


def is_clarification(result) -> bool:
    response = result.response.get("response") or {}
    response_type = response.get("response_type")
    if response_type in {"error"}:
        return True
    speech = (result.speech or "").lower()
    markers = ("which", "clarify", "what do you mean", "could you", "please specify", "?")
    return any(marker in speech for marker in markers)


def is_hallucination(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    allowed_entities: set[str],
) -> bool:
    changed = get_changed_entities(before, after)
    return any(entity_id not in allowed_entities for entity_id in changed)


def classify_outcome(
    result,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    *,
    expected_entity_ids: set[str] | None = None,
) -> dict[str, bool]:
    allowed = allowed_entities_for(*(expected_entity_ids or ()))
    return {
        "clarification": is_clarification(result),
        "hallucination": is_hallucination(before, after, allowed),
    }


def wait_and_assert(
    client,
    entity_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    timeout: float = 20.0,
) -> dict[str, Any]:
    return client.wait_for_state(entity_id, predicate, timeout=timeout)
