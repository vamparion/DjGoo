from __future__ import annotations

import random

from voice.media_policy import (
    CanonicalTrack,
    MediaCandidate,
    duration_is_plausible,
    pick_best_search_candidate,
    pick_radio_candidate,
    quality_rejection_reasons,
    ranked_search_candidates,
    search_match_is_confident,
    title_is_rejected,
)


def candidate(
    title: str,
    *,
    artist: str = "Example Artist",
    duration: int = 180,
    channel: str = "Example Artist Topic",
    index: int = 0,
    identifier: str = "one",
) -> MediaCandidate:
    return MediaCandidate(
        title=title,
        artists=(artist,),
        uri=f"media:{identifier}",
        duration_seconds=duration,
        channel=channel,
        result_index=index,
    )


def test_search_prefers_duration_matched_official_audio() -> None:
    canonical = CanonicalTrack("Best Song", ("Example Artist",), 181, "TEST123")
    selected = pick_best_search_candidate(
        [
            candidate("Best Song 1 Hour Loop", duration=3600, index=0, identifier="loop"),
            candidate("Best Song Official Audio", duration=183, index=1, identifier="official"),
            candidate("Best Song live", duration=242, index=2, identifier="live"),
        ],
        canonical,
    )
    assert selected is not None
    assert selected.uri == "media:official"


def test_duration_policy_rejects_video_longer_than_real_song() -> None:
    assert duration_is_plausible(194, 180)
    assert not duration_is_plausible(260, 180)
    assert not duration_is_plausible(3600, 180)


def test_title_policy_rejects_album_and_loop_sources() -> None:
    assert title_is_rejected("Best Song one hour loop")
    assert title_is_rejected("Artist Full Album 2026")
    assert not title_is_rejected("Best Song Official Music Video")


def test_quality_policy_rejects_unrequested_remixes_covers_and_instrumentals() -> None:
    assert quality_rejection_reasons(candidate("Best Song Remix"))
    assert quality_rejection_reasons(candidate("Best Song Cover"))
    assert quality_rejection_reasons(candidate("Best Song Instrumental"))
    requested = CanonicalTrack("Best Song Remix", ("Example Artist",), 180)
    assert not quality_rejection_reasons(candidate("Best Song Remix"), canonical=requested)


def test_ambiguous_or_wrong_artist_search_requires_a_choice() -> None:
    canonical = CanonicalTrack("Shadows", ("Lindsey Stirling",), 223)
    ranked = ranked_search_candidates(
        [
            candidate("Shadows", artist="Different Artist", duration=223, identifier="wrong"),
            candidate("Shadow", artist="Lindsey Stirling Tribute", duration=223, identifier="tribute"),
        ],
        canonical,
    )

    assert not search_match_is_confident(ranked, canonical)


def test_radio_uses_feedback_without_permanently_banning_artist() -> None:
    station = {
        "liked": [{"title": "Alpha First", "artist": "Alpha", "uri": "liked"}],
        "more_like": [{"title": "Alpha Second", "artist": "Alpha", "uri": "more"}],
        "less_like": [{"title": "Beta Old", "artist": "Beta", "uri": "less"}],
        "skipped": [{"title": "Beta Skip", "artist": "Beta", "uri": "skip"}],
        "banned": [],
        "recent": [],
    }
    selected = pick_radio_candidate(
        [
            candidate("New Alpha Hit", artist="Alpha", identifier="alpha"),
            candidate("New Beta Hit", artist="Beta", identifier="beta"),
        ],
        station,
        rng=random.Random(1),
    )
    assert selected is not None
    assert selected.artists == ("Alpha",)


def test_radio_applies_artist_cooldown() -> None:
    station = {
        "liked": [],
        "more_like": [],
        "less_like": [],
        "skipped": [],
        "banned": [],
        "recent": [{"title": "Alpha Last Song", "artist": "Alpha", "uri": "recent"}],
    }
    selected = pick_radio_candidate(
        [
            candidate("Another Alpha Song", artist="Alpha", identifier="alpha"),
            candidate("Fresh Gamma Song", artist="Gamma", identifier="gamma"),
        ],
        station,
        rng=random.Random(2),
    )
    assert selected is not None
    assert selected.artists == ("Gamma",)
