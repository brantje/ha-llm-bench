"""Static track catalog for deterministic media player behavior."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    """A playable track in the test catalog."""

    track_id: str
    title: str
    artist: str
    genre: str


CATALOG: tuple[Track, ...] = (
    Track("bohemian_rhapsody", "Bohemian Rhapsody", "Queen", "rock"),
    Track("so_what", "So What", "Miles Davis", "jazz"),
    Track("take_five", "Take Five", "Dave Brubeck", "jazz"),
)


def track_index(track: Track) -> int:
    """Return the index of a track in the catalog."""
    for index, item in enumerate(CATALOG):
        if item.track_id == track.track_id:
            return index
    raise ValueError(f"Unknown track: {track.track_id}")


def matches_search_query(track: Track, query: str) -> bool:
    """Return True if the track matches a free-text search query."""
    needle = query.strip().lower()
    if not needle:
        return False

    if (
        needle in track.title.lower()
        or needle in track.artist.lower()
        or needle in track.genre.lower()
        or track.genre.lower() in needle
    ):
        return True

    for token in needle.split():
        if len(token) < 2:
            continue
        if (
            token in track.title.lower()
            or token in track.artist.lower()
            or token == track.genre.lower()
        ):
            return True
    return False


def find_by_query(query: str) -> Track | None:
    """Match a track by title, artist, or genre (case-insensitive substring)."""
    for track in CATALOG:
        if matches_search_query(track, query):
            return track
    return None


def tracks_for_genre(genre: str) -> list[int]:
    """Return catalog indices for all tracks in a genre."""
    needle = genre.strip().lower()
    return [index for index, track in enumerate(CATALOG) if track.genre.lower() == needle]


def tracks_for_artist(artist: str) -> list[int]:
    """Return catalog indices for all tracks by an artist."""
    needle = artist.strip().lower()
    return [
        index
        for index, track in enumerate(CATALOG)
        if needle in track.artist.lower()
    ]


def playlist_for_track(index: int) -> list[int]:
    """Playlist used for next/previous: full catalog order."""
    return list(range(len(CATALOG)))
