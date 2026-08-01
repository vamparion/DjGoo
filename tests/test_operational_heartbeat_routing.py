from __future__ import annotations

from voice import operational_log


def test_redbot_voice_gateway_events_do_not_overwrite_listener_heartbeat(
    tmp_path, monkeypatch
) -> None:
    writes: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("DJGOO_COMPONENT_NAME", "redbot")
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, fields: writes.append((component, dict(fields))),
    )
    operational_log._COMPONENT_READY.update({"voice": False, "redbot": False})

    operational_log.log_event("voice.gateway.ready", port=47632)
    assert writes == []

    operational_log.log_event(
        "redbot.ready",
        guild_count=1,
        audio_loaded=True,
        discord_ready=True,
    )
    assert writes[-1][0] == "redbot"
    assert writes[-1][1]["ready"] is True


def test_voice_listener_activity_refreshes_only_voice_heartbeat(tmp_path, monkeypatch) -> None:
    writes: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("DJGOO_COMPONENT_NAME", "voice")
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, fields: writes.append((component, dict(fields))),
    )
    operational_log._COMPONENT_READY.update({"voice": False, "redbot": False})

    operational_log.log_event("voice.listener.ready", sample_rate=48000)
    operational_log.log_event("voice.hotkey.waiting", hotkey="F12")
    operational_log.log_event("redbot.heartbeat", discord_ready=True)

    assert [component for component, _ in writes] == ["voice", "voice"]
    assert all(fields["ready"] is True for _, fields in writes)
