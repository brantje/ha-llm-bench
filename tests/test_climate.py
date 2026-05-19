import pytest

from tests.conversation_test import run_entity_test
from ha_test.helpers import assert_climate_temp, setup_entity


def verify_temp_at_least_24(state):
    actual = float(state["attributes"].get("temperature", 0))
    assert actual >= 24, f"Expected temperature >= 24, got {actual}"


@pytest.mark.parametrize(
    ("command", "predicate", "verify"),
    [
        (
            "set living room temperature to 22 degrees",
            lambda state: abs(float(state["attributes"].get("temperature", 0)) - 22) <= 1.0,
            lambda state: assert_climate_temp(state, 22),
        ),
        (
            "increase the living room thermostat to 25",
            lambda state: float(state["attributes"].get("temperature", 0)) >= 24,
            verify_temp_at_least_24,
        ),
    ],
    ids=["set_temp", "increase_temp"],
)
def test_climate(request, ha_client, model, conversation, entity_snapshot, command, predicate, verify):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id="climate.living_room",
        predicate=predicate,
        setup=lambda client: setup_entity(client, "climate.living_room"),
        verify=verify,
    )
