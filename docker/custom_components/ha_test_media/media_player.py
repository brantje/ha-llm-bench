"""Media player platform for ha_test_media."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.core import HomeAssistant
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .catalog import (
    CATALOG,
    Track,
    find_by_query,
    matches_search_query,
    playlist_for_track,
    track_index,
    tracks_for_artist,
    tracks_for_genre,
)
from .const import CONF_AREA_ID, CONF_MEDIA_PLAYER, CONF_NAME, CONF_UNIQUE_ID, DEFAULT_VOLUME, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_MEDIA_PLAYER, default=[]): vol.All(
            cv.ensure_list,
            [
                {
                    vol.Required(CONF_NAME): cv.string,
                    vol.Required(CONF_UNIQUE_ID): cv.string,
                    vol.Optional(CONF_AREA_ID): cv.string,
                }
            ],
        )
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up media players from YAML."""
    players = config.get(CONF_MEDIA_PLAYER, [])
    if discovery_info:
        players = discovery_info.get(CONF_MEDIA_PLAYER, players)

    async_add_entities(
        HaTestMediaPlayer(hass, player_config) for player_config in players
    )


class HaTestMediaPlayer(MediaPlayerEntity):
    """Simulated media player backed by a static local catalog."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )
    _attr_device_class = "speaker"

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize the media player."""
        self._area_id = config.get(CONF_AREA_ID)
        self._attr_name = config[CONF_NAME]
        self._attr_unique_id = config[CONF_UNIQUE_ID]
        self._playlist: list[int] = list(range(len(CATALOG)))
        self._track_index = 0
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = DEFAULT_VOLUME
        self._attr_is_volume_muted = False
        self._clear_media_attributes()

    def _clear_media_attributes(self) -> None:
        self._attr_media_title = None
        self._attr_media_artist = None
        self._attr_media_album_name = None
        self._attr_media_content_id = None
        self._attr_media_content_type = None

    def _apply_track(self, index: int) -> None:
        track = CATALOG[index]
        self._track_index = index
        self._playlist = playlist_for_track(index)
        self._attr_media_title = track.title
        self._attr_media_artist = track.artist
        self._attr_media_album_name = track.genre
        self._attr_media_content_id = track.track_id
        self._attr_media_content_type = MediaType.MUSIC
        self._attr_state = MediaPlayerState.PLAYING

    async def async_added_to_hass(self) -> None:
        """Register area, display name, entity id, and conversation exposure."""
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        entity_id = self.entity_id
        if self.registry_entry is not None:
            updates: dict[str, str | None] = {
                "area_id": self._area_id,
                "name": "Living Room Speaker",
            }
            if entity_id != "media_player.living_room":
                updates["new_entity_id"] = "media_player.living_room"
            registry.async_update_entity(entity_id, **updates)
            entity_id = "media_player.living_room"
        async_expose_entity(self.hass, "conversation", entity_id, True)

    async def async_turn_on(self) -> None:
        """Turn on the player."""
        if self._attr_media_title:
            self._attr_state = MediaPlayerState.PLAYING
        else:
            self._attr_state = MediaPlayerState.IDLE

    async def async_turn_off(self) -> None:
        """Turn off the player."""
        self._attr_state = MediaPlayerState.OFF

    async def async_media_play(self) -> None:
        """Resume or start playback."""
        if self._attr_media_title:
            self._attr_state = MediaPlayerState.PLAYING
        else:
            self._attr_state = MediaPlayerState.IDLE

    async def async_media_pause(self) -> None:
        """Pause playback."""
        if self._attr_state == MediaPlayerState.PLAYING:
            self._attr_state = MediaPlayerState.PAUSED

    async def async_media_stop(self) -> None:
        """Stop playback."""
        self._attr_state = MediaPlayerState.IDLE
        self._clear_media_attributes()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        self._attr_volume_level = max(0.0, min(1.0, volume))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        self._attr_is_volume_muted = mute

    async def async_media_next_track(self) -> None:
        """Skip to the next track in the playlist."""
        if not self._playlist:
            return
        position = self._playlist.index(self._track_index)
        if position + 1 < len(self._playlist):
            self._apply_track(self._playlist[position + 1])
        else:
            self._apply_track(self._playlist[-1])

    async def async_media_previous_track(self) -> None:
        """Skip to the previous track in the playlist."""
        if not self._playlist:
            return
        position = self._playlist.index(self._track_index)
        if position > 0:
            self._apply_track(self._playlist[position - 1])
        else:
            self._apply_track(self._playlist[0])

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Search the static catalog for tracks matching the query."""
        results: list[BrowseMedia] = []

        for track in CATALOG:
            if matches_search_query(track, query.search_query):
                results.append(self._browse_media_for_track(track))

        if not results:
            track = find_by_query(query.search_query)
            if track is not None:
                results.append(self._browse_media_for_track(track))

        return SearchMedia(result=results)

    def _browse_media_for_track(self, track: Track) -> BrowseMedia:
        return BrowseMedia(
            media_class=MediaClass.MUSIC,
            media_content_id=track.track_id,
            media_content_type=MediaType.MUSIC,
            title=track.title,
            can_play=True,
            can_expand=False,
        )

    def play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play media matched against the static catalog."""
        track = None
        for item in CATALOG:
            if item.track_id == media_id:
                track = item
                break

        query = media_id
        search_query = kwargs.get("extra", {}).get("search_query")
        if search_query:
            query = f"{query} {search_query}"

        if track is None:
            track = find_by_query(query)
        if track is None:
            needle = query.lower()
            genre_indices = tracks_for_genre(needle)
            if genre_indices:
                self._playlist = genre_indices
                self._apply_track(genre_indices[0])
                return
            artist_indices = tracks_for_artist(needle)
            if artist_indices:
                self._playlist = artist_indices
                self._apply_track(artist_indices[0])
                return
            _LOGGER.warning("No catalog match for play_media query: %s", query)
            return

        self._playlist = playlist_for_track(track_index(track))
        self._apply_track(track_index(track))
