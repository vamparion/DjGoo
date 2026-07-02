from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from voice.command_queue import append_queue_item, command_to_queue_item, followup_to_queue_item
from voice.command_parser import PendingChoice, parse_command, parse_followup
from voice.listener_settings import voice_settings
from voice.secrets import load_project_secrets


SAMPLE_RATE = 16000
HOTKEYS = {
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


def record_chunk(seconds: float) -> np.ndarray:
    frames = int(SAMPLE_RATE * seconds)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def is_hotkey_down(hotkey: str) -> bool:
    if sys.platform != "win32":
        return False
    vk_code = HOTKEYS.get(hotkey.upper())
    if vk_code is None:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)


def wait_for_hotkey_press(hotkey: str, *, poll_seconds: float = 0.03) -> None:
    while not is_hotkey_down(hotkey):
        time.sleep(poll_seconds)


def record_while_hotkey_held(
    hotkey: str,
    *,
    min_seconds: float,
    max_seconds: float,
    block_seconds: float = 0.1,
) -> np.ndarray:
    block_frames = max(1, int(SAMPLE_RATE * block_seconds))
    max_frames = int(SAMPLE_RATE * max_seconds)
    min_frames = int(SAMPLE_RATE * min_seconds)
    chunks = []
    total_frames = 0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        while total_frames < max_frames:
            data, _overflowed = stream.read(block_frames)
            chunks.append(data.reshape(-1).copy())
            total_frames += len(chunks[-1])
            if total_frames >= min_frames and not is_hotkey_down(hotkey):
                break
    if not chunks:
        return np.array([], dtype="float32")
    return np.concatenate(chunks)


def transcribe(
    model: WhisperModel,
    audio: np.ndarray,
    *,
    language: str,
    beam_size: int,
    hotwords: str,
    initial_prompt: str,
) -> str:
    segments, _info = model.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        best_of=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 250},
        condition_on_previous_text=False,
        initial_prompt=initial_prompt or None,
        hotwords=hotwords or None,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def run(project_root: Path) -> None:
    secrets = load_project_secrets(project_root)
    voice_config = secrets.get("voice", {})
    settings = voice_settings(voice_config, project_root)

    print(f"Loading Whisper model {settings['model_name']} ({settings['compute_type']})...", flush=True)
    model = WhisperModel(settings["model_name"], device="cpu", compute_type=settings["compute_type"])
    if settings["push_to_talk"]:
        ready_message = f"DjGoo local voice listener is running. Hold {settings['hotkey']} and speak a command."
    else:
        ready_message = "DjGoo local voice listener is running. Say 'DjGoo ...' into the default mic."
    print(ready_message, flush=True)

    pending: PendingChoice | None = None
    while True:
        if settings["push_to_talk"]:
            wait_for_hotkey_press(settings["hotkey"])
            audio = record_while_hotkey_held(
                settings["hotkey"],
                min_seconds=settings["min_record_seconds"],
                max_seconds=settings["max_record_seconds"],
            )
        else:
            audio = record_chunk(settings["chunk_seconds"])
        transcript = transcribe(
            model,
            audio,
            language=settings["language"],
            beam_size=settings["beam_size"],
            hotwords=settings["hotwords"],
            initial_prompt=settings["initial_prompt"],
        )
        if not transcript:
            continue

        print(f"Heard: {transcript}", flush=True)
        now = time.monotonic()
        if pending is not None:
            followup = parse_followup(transcript, pending, now=now)
            if followup.action == "expired":
                append_queue_item(settings["queue_path"], followup_to_queue_item(followup, transcript=transcript))
                pending = None
                continue
            if followup.action in {"choose", "neither", "cancel"}:
                append_queue_item(settings["queue_path"], followup_to_queue_item(followup, transcript=transcript))
                pending = None
                continue

        command = parse_command(transcript, require_wake=settings["require_wake_word"])
        if command.intent in {"ignore", "unknown"}:
            continue

        append_queue_item(settings["queue_path"], command_to_queue_item(command, transcript=transcript))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local DjGoo voice listener.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="DiscordBot project root.",
    )
    args = parser.parse_args()

    try:
        run(Path(args.project_root).resolve())
    except KeyboardInterrupt:
        print("DjGoo local voice listener stopped.")
        return 0
    except Exception as exc:
        print(f"DjGoo local voice listener crashed: {exc!r}", file=sys.stderr, flush=True)
        raise
    return 1


if __name__ == "__main__":
    sys.exit(main())
