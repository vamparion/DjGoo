from __future__ import annotations

from pathlib import Path

from voice.command_parser import parse_command
from voice.request_ledger import RequestLedger


def test_request_timing_phrases() -> None:
    next_request = parse_command("play next Sandstorm", require_wake=False)
    now_request = parse_command("play now Sandstorm", require_wake=False)
    later_request = parse_command("queue request Sandstorm", require_wake=False)

    assert (next_request.intent, next_request.query) == ("play", "Sandstorm")
    assert (now_request.intent, now_request.query) == ("play_now", "Sandstorm")
    assert (later_request.intent, later_request.query) == (
        "queue_request",
        "Sandstorm",
    )


def test_plain_request_defaults_to_next() -> None:
    command = parse_command("request Darude Sandstorm", require_wake=False)

    assert command.intent == "play"
    assert command.query == "Darude Sandstorm"


def test_request_ledger_survives_new_instance(tmp_path: Path) -> None:
    path = tmp_path / "requests.json"
    first = RequestLedger(path)
    first.add(
        123,
        track_key="track-key",
        title="Sandstorm",
        timing="now",
        requester_id=456,
        requester_name="Vamp",
    )

    second = RequestLedger(path)
    assert second.pending_keys(123) == {"track-key"}
    consumed = second.consume(123, "track-key")

    assert consumed is not None
    assert consumed["requester_name"] == "Vamp"
    assert consumed["timing"] == "now"
    assert second.count(123) == 0
