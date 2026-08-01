from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

import tools.djgoo_stack as stack
from tools.djgoo_stack import ComponentSpec, heartbeat_ready, process_record_matches


def _ready() -> bool:
    return True


def test_process_record_requires_creation_time_and_command_markers(tmp_path: Path) -> None:
    marker = "djgoo-supervisor-test-marker"
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(tmp_path), marker]
    )
    try:
        proc = psutil.Process(process.pid)
        spec = ComponentSpec(
            name="test",
            command=[],
            cwd=tmp_path,
            command_markers=(str(tmp_path), marker),
            ready=_ready,
            ready_timeout=1,
        )
        valid_record = {
            "pid": process.pid,
            "create_time": proc.create_time(),
        }
        assert process_record_matches(valid_record, spec)
        assert not process_record_matches(
            {**valid_record, "create_time": proc.create_time() - 100},
            spec,
        )
        wrong_spec = ComponentSpec(
            name="test",
            command=[],
            cwd=tmp_path,
            command_markers=("missing-marker",),
            ready=_ready,
            ready_timeout=1,
        )
        assert not process_record_matches(valid_record, wrong_spec)
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_dead_process_record_is_not_owned(tmp_path: Path) -> None:
    spec = ComponentSpec(
        name="test",
        command=[],
        cwd=tmp_path,
        command_markers=("anything",),
        ready=_ready,
        ready_timeout=1,
    )
    assert not process_record_matches({"pid": 999_999_999, "create_time": time.time()}, spec)


def test_heartbeat_requires_current_pid_freshness_and_fields(tmp_path: Path, monkeypatch) -> None:
    pid_dir = tmp_path / "pids"
    health_dir = tmp_path / "health"
    pid_dir.mkdir()
    health_dir.mkdir()
    monkeypatch.setattr(stack, "PID_DIR", pid_dir)
    monkeypatch.setattr(stack, "HEALTH_DIR", health_dir)

    (pid_dir / "redbot.json").write_text(json.dumps({"pid": 1234}), encoding="utf-8")
    heartbeat = {
        "pid": 1234,
        "timestamp": time.time(),
        "ready": True,
        "audio_loaded": True,
        "discord_ready": True,
    }
    (health_dir / "redbot.json").write_text(json.dumps(heartbeat), encoding="utf-8")

    assert heartbeat_ready(
        "redbot",
        max_age_seconds=15,
        required_fields={"audio_loaded": True, "discord_ready": True},
    )

    (health_dir / "redbot.json").write_text(
        json.dumps({**heartbeat, "pid": 9999}),
        encoding="utf-8",
    )
    assert not heartbeat_ready("redbot", max_age_seconds=15)

    (health_dir / "redbot.json").write_text(
        json.dumps({**heartbeat, "timestamp": time.time() - 60}),
        encoding="utf-8",
    )
    assert not heartbeat_ready("redbot", max_age_seconds=15)
