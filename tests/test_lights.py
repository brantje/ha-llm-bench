import pytest

from tests.conversation_test import run_entity_test
from ha_test.helpers import setup_entity


@pytest.mark.parametrize(
    ("command", "setup", "predicate"),
    [
        (
            "turn lamp x off",
            lambda client: setup_entity(client, "light.lamp_x"),
            lambda state: state["state"] == "off",
        ),
        (
            "turn lamp x on",
            lambda client: (
                client.set_helper_state("input_boolean.lamp_x_power", False),
                client.set_helper_state("input_number.lamp_x_brightness", 0),
            ),
            lambda state: state["state"] == "on",
        ),
        (
            "set lamp x brightness to 50 percent",
            lambda client: setup_entity(client, "light.lamp_x"),
            lambda state: state["state"] == "on"
            and int(state["attributes"].get("brightness", 0)) <= 130,
        ),
    ],
    ids=["turn_off", "turn_on", "dim"],
)
def test_lights(request, ha_client, model, conversation, entity_snapshot, command, setup, predicate):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id="light.lamp_x",
        predicate=predicate,
        setup=setup,
    )
