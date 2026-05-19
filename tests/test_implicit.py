import pytest

from tests.conversation_test import run_entity_test, run_implicit_choice_test
from ha_test.helpers import setup_entity


@pytest.mark.parametrize(
    ("command", "entity_id", "setup", "predicate"),
    [
        (
            "turn off the light",
            "light.lamp_x",
            lambda client: setup_entity(client, "light.lamp_x"),
            lambda state: state["state"] == "off",
        ),
        (
            "turn on the light",
            "light.lamp_x",
            lambda client: (
                client.set_helper_state("input_boolean.lamp_x_power", False),
                client.set_helper_state("input_number.lamp_x_brightness", 0),
            ),
            lambda state: state["state"] == "on",
        ),
        (
            "make it warmer",
            "input_number.living_room_temp",
            lambda client: setup_entity(client, "climate.living_room"),
            lambda state: float(state["state"]) > 21,
        ),
    ],
    ids=["turn_off_light", "turn_on_light", "make_warmer"],
)
def test_implicit(
    request, ha_client, model, conversation, entity_snapshot, command, entity_id, setup, predicate
):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id=entity_id,
        predicate=predicate,
        setup=setup,
    )


def test_turn_on_the_thing(request, ha_client, model, conversation, entity_snapshot):
    run_implicit_choice_test(
        nodeid=request.node.nodeid,
        model=model,
        command="turn on the thing",
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        choices=[
            ("light.lamp_x", lambda state: state["state"] == "on"),
            ("switch.fan_switch", lambda state: state["state"] == "on"),
        ],
        setup=lambda client: (
            client.set_helper_state("input_boolean.lamp_x_power", False),
            client.set_helper_state("input_number.lamp_x_brightness", 0),
            client.set_helper_state("input_boolean.fan_switch", False),
        ),
    )
