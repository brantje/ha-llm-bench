import pytest

from tests.conversation_test import run_entity_test
from ha_test.helpers import setup_entity


@pytest.mark.parametrize(
    ("command", "initial", "predicate"),
    [
        ("turn the tv switch on", False, lambda state: state["state"] == "on"),
        ("switch tv switch off", True, lambda state: state["state"] == "off"),
    ],
    ids=["turn_on", "turn_off"],
)
def test_switches(
    request, ha_client, model, conversation, entity_snapshot, command, initial, predicate
):
    def setup(client):
        setup_entity(client, "switch.tv_switch")
        client.set_helper_state("input_boolean.tv_switch", initial)

    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id="switch.tv_switch",
        predicate=predicate,
        setup=setup,
    )
