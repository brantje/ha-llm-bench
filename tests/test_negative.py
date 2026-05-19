import pytest

from tests.conversation_test import run_negative_test


@pytest.mark.parametrize(
    "command",
    [
        "unlock the moon door",
        "turn the dishwasher into a spaceship",
    ],
)
def test_negative(request, ha_client, model, conversation, entity_snapshot, command):
    run_negative_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
    )
