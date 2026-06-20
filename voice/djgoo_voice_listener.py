from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from voice.command_queue import append_queue_item, command_to_queue_item, followup_to_queue_item
from voice.command_parser import PendingChoice, parse_command, parse_followup
from voice.overlay import send_overlay
from voice.secrets import load_project_secrets


SAMPLE_RATE = 16000


def record_chunk(seconds: float) -> np.ndarray:
    frames = int(SAMPLE_RATE * seconds)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def transcribe(model: WhisperModel, audio: np.ndarray, *, language: str) -> str:
    segments, _info = model.transcribe(
        audio,
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def run(project_root: Path) -> None:
    secrets = load_project_secrets(project_root)
    webhook_url = secrets.get("webhook_url", "")
    voice_config = secrets.get("voice", {})
    model_name = voice_config.get("model", "base.en")
    chunk_seconds = float(voice_config.get("chunk_seconds", 4))
    language = voice_config.get("language", "en")
    compute_type = voice_config.get("compute_type", "int8")
    queue_path = Path(voice_config.get("queue_path") or project_root / "data" / "voice-command-queue.jsonl")

    print(f"Loading Whisper model {model_name} ({compute_type})...", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
    print("DjGoo local voice listener is running. Say 'DjGoo ...' into the default mic.", flush=True)
    send_overlay(
        webhook_url,
        "DjGoo voice listener started",
        "Listening on the default Windows microphone for `DjGoo ...`.",
    )

    pending: PendingChoice | None = None
    while True:
        audio = record_chunk(chunk_seconds)
        transcript = transcribe(model, audio, language=language)
        if not transcript:
            continue

        print(f"Heard: {transcript}", flush=True)
        now = time.monotonic()
        if pending is not None:
            followup = parse_followup(transcript, pending, now=now)
            if followup.action == "expired":
                append_queue_item(queue_path, followup_to_queue_item(followup, transcript=transcript))
                pending = None
                continue
            if followup.action in {"choose", "neither", "cancel"}:
                append_queue_item(queue_path, followup_to_queue_item(followup, transcript=transcript))
                pending = None
                continue

        command = parse_command(transcript)
        if command.intent == "ignore":
            continue

        append_queue_item(queue_path, command_to_queue_item(command, transcript=transcript))


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
