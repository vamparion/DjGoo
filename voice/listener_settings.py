from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


DEFAULT_COMMAND_HOTWORDS = (
    "DjGoo DJ Goo DeeJay play skip pause resume stop queue volume radio seek remove move "
    "shuffle repeat favorite history like this more like this less like this "
    "don't play this again official audio Sandstorm"
)


def voice_settings(voice_config: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    push_to_talk = bool(voice_config.get("push_to_talk", True))
    hotkey = str(voice_config.get("hotkey", "F12")).upper()
    chunk_seconds = float(voice_config.get("chunk_seconds", 4.0))
    beam_size = max(1, int(voice_config.get("beam_size", 8)))
    min_record_seconds = float(voice_config.get("min_record_seconds", 0.25))
    hotkey_beam_size = max(
        1,
        int(voice_config.get("hotkey_beam_size", min(3, beam_size))),
    )
    return {
        # distil-large-v3 remains the accuracy model. Push-to-talk uses a smaller
        # first-pass beam and only spends more work when a result is uncertain.
        "model_name": str(voice_config.get("model", "distil-large-v3")),
        "device": str(voice_config.get("device", "cpu")),
        "compute_type": str(voice_config.get("compute_type", "int8")),
        "cpu_threads": int(voice_config.get("cpu_threads", 0)),
        "language": str(voice_config.get("language", "en")),
        "beam_size": beam_size,
        "hotkey_beam_size": hotkey_beam_size,
        "recognition_retry_beam_size": max(
            hotkey_beam_size,
            int(voice_config.get("recognition_retry_beam_size", 5)),
        ),
        "vad_filter": bool(voice_config.get("vad_filter", True)),
        # Push-to-talk already provides speech boundaries. Disabling VAD on that
        # path prevents short commands from being discarded as empty.
        "hotkey_vad_filter": bool(
            voice_config.get("hotkey_vad_filter", False)
        ),
        "vad_min_silence_ms": int(voice_config.get("vad_min_silence_ms", 180)),
        "vad_speech_pad_ms": int(voice_config.get("vad_speech_pad_ms", 120)),
        "min_avg_logprob": float(voice_config.get("min_avg_logprob", -1.05)),
        "max_no_speech_prob": float(voice_config.get("max_no_speech_prob", 0.62)),
        "silence_rms_threshold": float(voice_config.get("silence_rms_threshold", 0.0015)),
        "block_seconds": float(voice_config.get("block_seconds", 0.02)),
        "preroll_seconds": float(voice_config.get("preroll_seconds", 0.28)),
        "release_tail_seconds": float(voice_config.get("release_tail_seconds", 0.18)),
        "chunk_seconds": chunk_seconds,
        "min_record_seconds": min_record_seconds,
        # Existing installations commonly contain the old 0.25-second value.
        # This separate setting improves them without rewriting user secrets.
        "hotkey_min_record_seconds": max(
            min_record_seconds,
            float(voice_config.get("hotkey_min_record_seconds", 0.90)),
        ),
        "short_audio_pad_seconds": max(
            0.0,
            float(voice_config.get("short_audio_pad_seconds", 1.25)),
        ),
        "tap_record_seconds": float(voice_config.get("tap_record_seconds", chunk_seconds)),
        "max_record_seconds": float(voice_config.get("max_record_seconds", 10.0)),
        "hotkey_poll_seconds": float(voice_config.get("hotkey_poll_seconds", 0.01)),
        # Retained for configuration compatibility. The continuous-stream listener no
        # longer opens emergency recording windows unless a future listener mode uses them.
        "emergency_voice_controls": bool(voice_config.get("emergency_voice_controls", False)),
        "emergency_listen_interval_seconds": float(
            voice_config.get("emergency_listen_interval_seconds", 0.2)
        ),
        "emergency_chunk_seconds": float(voice_config.get("emergency_chunk_seconds", 1.6)),
        "input_device": voice_config.get("input_device"),
        "queue_path": Path(
            voice_config.get("queue_path")
            or project_root / "data" / "voice-command-queue.jsonl"
        ),
        "push_to_talk": push_to_talk,
        "hotkey": hotkey,
        "require_wake_word": bool(voice_config.get("require_wake_word", not push_to_talk)),
        "feedback_beeps": bool(voice_config.get("feedback_beeps", True)),
        "corrections": voice_config.get("corrections"),
        "hotwords": str(voice_config.get("hotwords", DEFAULT_COMMAND_HOTWORDS)),
        "initial_prompt": str(
            voice_config.get(
                "initial_prompt",
                "A short English Discord music command. Preserve artist names and song titles exactly. "
                "Examples: play Sandstorm; skip; seek one minute; remove number three; radio Metallica.",
            )
        ),
    }
