"""Unit tests for entity catalog and hallucination detection."""

from __future__ import annotations

from ha_test.helpers import allowed_entities_for, is_hallucination


def _state(entity_id: str, state: str) -> dict:
    return {"entity_id": entity_id, "state": state}


def test_allowed_entities_for_catalog_entity_includes_related_helpers():
    allowed = allowed_entities_for("climate.living_room")

    assert "climate.living_room" in allowed
    assert "input_number.living_room_temp" in allowed
    assert "input_boolean.living_room_heater" in allowed
    assert "light.lamp_x" not in allowed


def test_allowed_entities_for_helper_includes_parent_catalog_entity():
    allowed = allowed_entities_for("input_number.living_room_temp")

    assert "input_number.living_room_temp" in allowed
    assert "climate.living_room" in allowed
    assert "input_select.living_room_hvac" in allowed


def test_allowed_entities_for_implicit_choice_unions_scopes():
    allowed = allowed_entities_for("light.lamp_x", "switch.tv_switch")

    assert "light.lamp_x" in allowed
    assert "input_boolean.lamp_x_power" in allowed
    assert "switch.tv_switch" in allowed
    assert "input_boolean.tv_switch" in allowed
    assert "climate.living_room" not in allowed


def test_is_hallucination_false_when_only_expected_climate_helpers_change():
    before = {
        "climate.living_room": _state("climate.living_room", "heat"),
        "input_number.living_room_temp": _state("input_number.living_room_temp", "21"),
    }
    after = {
        "climate.living_room": _state("climate.living_room", "heat"),
        "input_number.living_room_temp": _state("input_number.living_room_temp", "22"),
    }
    allowed = allowed_entities_for("climate.living_room")

    assert is_hallucination(before, after, allowed) is False


def test_is_hallucination_true_when_unrelated_entity_changes():
    before = {
        "climate.living_room": _state("climate.living_room", "heat"),
        "switch.tv_switch": _state("switch.tv_switch", "off"),
    }
    after = {
        "climate.living_room": _state("climate.living_room", "heat"),
        "switch.tv_switch": _state("switch.tv_switch", "on"),
    }
    allowed = allowed_entities_for("climate.living_room")

    assert is_hallucination(before, after, allowed) is True


def test_is_hallucination_true_for_negative_test_when_any_entity_changes():
    before = {"light.lamp_x": _state("light.lamp_x", "off")}
    after = {"light.lamp_x": _state("light.lamp_x", "on")}

    assert is_hallucination(before, after, set()) is True
