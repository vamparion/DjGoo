from __future__ import annotations

from voice import operational_log


def test_redbot_command_event_does_not_replace_readiness_heartbeat(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setenv("DJGOO_COMPONENT_NAME", "redbot")
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, **kwargs: calls.append((component, kwargs)),
    )
    operational_log._COMPONENT_READY["redbot"] = True

    operational_log.log_event(
        "redbot.command.invoke",
        command="play",
        kwargs={"query": "https://www.youtube.com/watch?v=example"},
    )

    assert calls == []


def test_redbot_authoritative_heartbeat_keeps_required_readiness_fields(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setenv("DJGOO_COMPONENT_NAME", "redbot")
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, **kwargs: calls.append((component, kwargs)),
    )
    operational_log._COMPONENT_READY["redbot"] = False

    operational_log.log_event(
        "redbot.heartbeat",
        guild_count=1,
        audio_loaded=True,
        discord_ready=True,
        voice_gateway_ready=True,
    )

    assert len(calls) == 1
    component, kwargs = calls[0]
    assert component == "redbot"
    assert kwargs["fields"] == {
        "ready": True,
        "event": "redbot.heartbeat",
        "guild_count": 1,
        "audio_loaded": True,
        "discord_ready": True,
    }
