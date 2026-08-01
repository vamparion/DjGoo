from __future__ import annotations

from pathlib import Path

import voice.operational_log as operational_log


def test_voice_activity_does_not_report_ready_before_model_load(tmp_path: Path, monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, fields: captured.append((component, dict(fields))),
    )
    operational_log._COMPONENT_READY["voice"] = False

    operational_log.log_event("voice.listener.starting", model="distil-large-v3")
    assert captured[-1][0] == "voice"
    assert captured[-1][1]["ready"] is False

    operational_log.log_event("voice.listener.ready")
    assert captured[-1][1]["ready"] is True

    operational_log.log_event("voice.hotkey.waiting")
    assert captured[-1][1]["ready"] is True

    operational_log.log_event("voice.listener.crashed")
    assert captured[-1][1]["ready"] is False


def test_redbot_heartbeat_includes_health_fields(tmp_path: Path, monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []
    monkeypatch.setenv("DJGOO_EVENT_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(
        operational_log,
        "write_heartbeat",
        lambda component, fields: captured.append((component, dict(fields))),
    )
    operational_log._COMPONENT_READY["redbot"] = False

    operational_log.log_event(
        "redbot.heartbeat",
        guild_count=1,
        audio_loaded=True,
        discord_ready=True,
    )
    component, fields = captured[-1]
    assert component == "redbot"
    assert fields["ready"] is True
    assert fields["audio_loaded"] is True
    assert fields["discord_ready"] is True
