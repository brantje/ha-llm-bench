import pytest

from tests.conversation_test import run_entity_test
from ha_test.helpers import setup_entity


def _attrs(state: dict) -> dict:
    return state.get("attributes") or {}


def setup_baseline(client):
    setup_entity(client, "media_player.living_room")


def setup_playing_bohemian(client):
    setup_entity(client, "media_player.living_room")
    client.call_service(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.living_room",
            "media_content_id": "Bohemian Rhapsody",
            "media_content_type": "music",
        },
    )


def setup_playing_take_five(client):
    setup_entity(client, "media_player.living_room")
    client.call_service(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.living_room",
            "media_content_id": "Take Five",
            "media_content_type": "music",
        },
    )


@pytest.mark.parametrize(
    ("command", "setup", "predicate"),
    [
        (
            "play Bohemian Rhapsody on the living room speaker",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and "bohemian" in (_attrs(state).get("media_title") or "").lower(),
        ),
        (
            "play some jazz in the living room",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and (_attrs(state).get("media_album_name") or "").lower() == "jazz",
        ),
        (
            "play Miles Davis in the living room",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and "miles davis" in (_attrs(state).get("media_artist") or "").lower(),
        ),
        (
            "pause the living room speaker",
            setup_playing_bohemian,
            lambda state: state["state"] == "paused",
        ),
        (
            "turn off the living room speaker",
            setup_playing_bohemian,
            lambda state: state["state"] in ("idle", "off"),
        ),
        (
            "mute the living room speaker",
            setup_baseline,
            lambda state: _attrs(state).get("is_volume_muted") is True,
        ),
        (
            "set living room speaker volume to 50 percent",
            setup_baseline,
            lambda state: 0.4 <= float(_attrs(state).get("volume_level", 0)) <= 0.6,
        ),
        (
            "skip to the next track on the living room speaker",
            setup_playing_bohemian,
            lambda state: state["state"] == "playing"
            and "so what" in (_attrs(state).get("media_title") or "").lower(),
        ),
        (
            "go to the previous track on the living room speaker",
            setup_playing_take_five,
            lambda state: state["state"] == "playing"
            and "so what" in (_attrs(state).get("media_title") or "").lower(),
        ),
    ],
    ids=[
        "play_track",
        "play_genre",
        "play_artist",
        "pause",
        "stop",
        "mute",
        "volume",
        "next_track",
        "previous_track",
    ],
)
def test_media_player(
    request, ha_client, model, conversation, entity_snapshot, command, setup, predicate
):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id="media_player.living_room",
        predicate=predicate,
        setup=setup,
    )


@pytest.mark.parametrize(
    ("command", "setup", "predicate"),
    [
        (
            "play Bohemian Rhapsody in the living room",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and "bohemian" in (_attrs(state).get("media_title") or "").lower(),
        ),
        (
            "play some jazz in the living room",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and (_attrs(state).get("media_album_name") or "").lower() == "jazz",
        ),
        (
            "play Miles Davis in the living room",
            setup_baseline,
            lambda state: state["state"] == "playing"
            and "miles davis" in (_attrs(state).get("media_artist") or "").lower(),
        ),
        (
            "pause the living room",
            setup_playing_bohemian,
            lambda state: state["state"] == "paused",
        ),
        (
            "turn off music in the living room",
            setup_playing_bohemian,
            lambda state: state["state"] in ("idle", "off", "paused"),
        ),
        (
            "set the living room volume to 50 percent",
            setup_baseline,
            lambda state: 0.4 <= float(_attrs(state).get("volume_level", 0)) <= 0.6,
        ),
        (
            "skip to the next track in the living room",
            setup_playing_bohemian,
            lambda state: state["state"] == "playing"
            and "so what" in (_attrs(state).get("media_title") or "").lower(),
        ),
        (
            "go to the previous track in the living room",
            setup_playing_take_five,
            lambda state: state["state"] == "playing"
            and "so what" in (_attrs(state).get("media_title") or "").lower(),
        ),
    ],
    ids=[
        "play_track",
        "play_genre",
        "play_artist",
        "pause",
        "stop",
        "volume",
        "next_track",
        "previous_track",
    ],
)
def test_media_player_without_speaker(
    request, ha_client, model, conversation, entity_snapshot, command, setup, predicate
):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id="media_player.living_room",
        predicate=predicate,
        setup=setup,
    )
