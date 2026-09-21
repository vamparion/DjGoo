from voice.gaming_session import GamingSessionStore


def test_profiles_roles_and_host_only_settings(tmp_path) -> None:
    store = GamingSessionStore(tmp_path / "gaming.json")
    profile = store.create_profile("Vera", role="member", device_id="phone")
    assert store.profile(profile["token"])["username"] == "Vera"
    promoted = store.set_role(0, profile["id"], "moderator", actor_role="host")
    assert promoted["role"] == "moderator"
    settings = store.update_settings(0, {"explicit_policy": "reject"}, actor_role="host")
    assert settings["explicit_policy"] == "reject"


def test_round_robin_preserves_each_requesters_order(tmp_path) -> None:
    store = GamingSessionStore(tmp_path / "gaming.json")
    entries = [
        {"entry_id": "a1", "requester_key": "a"},
        {"entry_id": "a2", "requester_key": "a"},
        {"entry_id": "b1", "requester_key": "b"},
        {"entry_id": "c1", "requester_key": "c"},
        {"entry_id": "b2", "requester_key": "b"},
    ]
    assert store.fair_order(entries) == ["a1", "b1", "c1", "a2", "b2"]


def test_guest_votes_execute_once_at_threshold(tmp_path) -> None:
    store = GamingSessionStore(tmp_path / "gaming.json")
    first = store.cast_vote(1, track_key="song", action="skip", voter_key="one", role="guest")
    duplicate = store.cast_vote(1, track_key="song", action="skip", voter_key="one", role="guest")
    second = store.cast_vote(1, track_key="song", action="skip", voter_key="two", role="guest")
    assert not first.execute
    assert duplicate.duplicate
    assert second.execute


def test_queue_limit_and_undo(tmp_path) -> None:
    store = GamingSessionStore(tmp_path / "gaming.json")
    pending = [{"requester_key": "u"}, {"requester_key": "u"}, {"requester_key": "u"}]
    assert store.queue_limit_reached(1, "u", pending)
    store.record_undo(1, "skip", {"uri": "track:one"})
    assert store.pop_undo(1)["payload"]["uri"] == "track:one"
    assert store.pop_undo(1) is None
