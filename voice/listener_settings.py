from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


DEFAULT_COMMAND_HOTWORDS = (
    "DjGoo DJ Goo DeeJay play skip pause resume stop queue volume radio "
    "like this more like this less like this don't play this again Sandstorm"
)


def voice_settings(voice_config: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    push_to_talk = bool(voice_config.get("push_to_talk", True))
    hotkey = str(voice_config.get("hotkey", "F12")).upper()
    return {
        "model_name": voice_config.get("model", "small.en"),
        "chunk_seconds": float(voice_config.get("chunk_seconds", 4)),
        "silence_rms_threshold": float(voice_config.get("silence_rms_threshold", 0.002)),
        "min_record_seconds": float(voice_config.get("min_record_seconds", 0.4)),
        "tap_record_seconds": float(voice_config.get("tap_record_seconds", voice_config.get("chunk_seconds", 4))),
        "emergency_voice_controls": bool(voice_config.get("emergency_voice_controls", True)),
        "emergency_listen_interval_seconds": float(voice_config.get("emergency_listen_interval_seconds", 0.2)),
        "emergency_chunk_seconds": float(voice_config.get("emergency_chunk_seconds", 1.6)),
        "max_record_seconds": float(voice_config.get("max_record_seconds", 8)),
        "language": voice_config.get("language", "en"),
        "compute_type": voice_config.get("compute_type", "int8"),
        "input_device": voice_config.get("input_device"),
        "queue_path": Path(voice_config.get("queue_path") or project_root / "data" / "voice-command-queue.jsonl"),
        "push_to_talk": push_to_talk,
        "hotkey": hotkey,
        "require_wake_word": bool(voice_config.get("require_wake_word", not push_to_talk)),
        "beam_size": int(voice_config.get("beam_size", 5)),
        "hotwords": str(voice_config.get("hotwords", DEFAULT_COMMAND_HOTWORDS)),
        "initial_prompt": str(
            voice_config.get(
                "initial_prompt",
                "Short Discord music bot commands. Examples: play Sandstorm, skip, pause, resume, stop, radio Sandstorm.",
            )
        ),
    }
