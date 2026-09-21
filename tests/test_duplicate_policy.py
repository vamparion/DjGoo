from voice.duplicate_policy import allows_duplicate, filter_automatic_duplicates


def test_only_explicit_player_sources_allow_duplicates() -> None:
    assert allows_duplicate("chat")
    assert allows_duplicate("voice")
    assert not allows_duplicate("mini_player")
    assert not allows_duplicate("playlist")
    assert not allows_duplicate("radio")
    assert not allows_duplicate("recovery")


def test_system_duplicates_are_removed_but_discord_manual_repeat_survives() -> None:
    tracks, skipped = filter_automatic_duplicates(
        [
            {"title": "One", "uri": "same", "source": "playlist"},
            {"title": "One", "uri": "same", "source": "playlist"},
            {"title": "One", "uri": "same", "source": "chat"},
        ]
    )

    assert skipped == 1
    assert [track["source"] for track in tracks] == ["playlist", "chat"]
