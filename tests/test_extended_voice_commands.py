from voice.command_parser import parse_command


def test_seek_commands() -> None:
    assert parse_command("seek 1:30", require_wake=False).value == 90
    assert parse_command("go to two minutes", require_wake=False).value == 120


def test_queue_management_commands() -> None:
    remove = parse_command("remove number three from the queue", require_wake=False)
    assert remove.intent == "remove_queue"
    assert remove.value == 3
    assert parse_command("shuffle the queue", require_wake=False).intent == "shuffle_queue"


def test_radio_and_library_commands() -> None:
    start = parse_command("radio 80s", require_wake=False)
    stop = parse_command("radio off", require_wake=False)

    assert start.intent == "start_radio"
    assert start.query == "80s"
    assert stop.intent == "stop_radio"
    assert parse_command("don't like this", require_wake=False).intent == "station_less_like_current"
    assert parse_command("undo last ban", require_wake=False).intent == "undo_station_ban"
    assert parse_command("undo that", require_wake=False).intent == "gaming_undo"
    assert parse_command("add to favorites", require_wake=False).intent == "favorite_current"
    assert parse_command("toggle repeat", require_wake=False).intent == "repeat"
    assert parse_command("toggle autoplay", require_wake=False).intent == "autoplay"
