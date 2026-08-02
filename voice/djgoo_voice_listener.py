from __future__ import annotations

import argparse
import ctypes
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from voice.audio_capture import PushToTalkAudioCapture, audio_metrics, prepare_for_whisper
from voice.command_queue import append_queue_item, command_to_queue_item
from voice.command_parser import parse_command
from voice.corrections import apply_corrections, correction_hotwords, load_corrections
from voice.input_binding import ButtonWaiter, COMMON_BUTTONS, is_button_down
from voice.listener_settings import voice_settings
from voice.operational_log import log_event
from voice.secrets import load_project_secrets


# Keep the original listener entrypoint compatible with every button accepted by
# the Host and recipient UIs. This makes generalized binding intrinsic to the
# listener rather than depending on a supervisor-side module substitution.
HOTKEYS = dict(COMMON_BUTTONS)
HotkeyWaiter = ButtonWaiter

if sys.platform == "win32":
    ctypes.windll.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    ctypes.windll.user32.GetAsyncKeyState.restype = ctypes.c_short


@dataclass(frozen=True)
class SpeechResult:
    text: str
    avg_logprob: float
    no_speech_prob: float
    duration_seconds: float


def is_hotkey_down(hotkey: str) -> bool:
    return is_button_down(hotkey)


def resolve_input_device(configured: object) -> int | str | None:
    if configured is None or str(configured).strip() == "":
        return None
    if isinstance(configured, int):
        return configured
    text = str(configured).strip()
    if text.isdigit():
        return int(text)
    lowered = text.lower()
    matches: list[int] = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        if lowered in str(device.get("name", "")).lower():
            matches.append(index)
    if not matches:
        raise ValueError(f"No microphone matched {configured!r}")
    return matches[0]


def input_device_summary(device: int | str | None) -> dict:
    try:
        default_device = sd.default.device
        default_input = list(default_device)[0] if not isinstance(default_device, int) else default_device
        selected = default_input if device is None else device
        info = sd.query_devices(selected, "input")
        return {
            "configured": device,
            "selected": selected,
            "name": info.get("name"),
            "default_input": default_input,
            "default_samplerate": info.get("default_samplerate"),
            "max_input_channels": info.get("max_input_channels"),
        }
    except Exception as exc:
        return {"configured": device, "error": f"{type(exc).__name__}: {exc}"}


def transcribe(
    model: WhisperModel,
    audio: np.ndarray,
    *,
    language: str,
    beam_size: int,
    hotwords: str,
    initial_prompt: str,
    vad_filter: bool,
    vad_min_silence_ms: int,
    vad_speech_pad_ms: int,
) -> SpeechResult:
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        best_of=beam_size,
        temperature=0.0,
        vad_filter=vad_filter,
        vad_parameters={
            "min_silence_duration_ms": vad_min_silence_ms,
            "speech_pad_ms": vad_speech_pad_ms,
        },
        condition_on_previous_text=False,
        initial_prompt=initial_prompt or None,
        hotwords=hotwords or None,
    )
    completed = list(segments)
    text = " ".join(segment.text.strip() for segment in completed if segment.text.strip()).strip()
    if not completed:
        return SpeechResult(text="", avg_logprob=float("-inf"), no_speech_prob=1.0, duration_seconds=0.0)

    weights = [max(0.05, float(segment.end) - float(segment.start)) for segment in completed]
    weight_total = sum(weights)
    avg_logprob = sum(float(segment.avg_logprob) * weight for segment, weight in zip(completed, weights)) / weight_total
    no_speech_prob = max(float(segment.no_speech_prob) for segment in completed)
    duration = max(float(segment.end) for segment in completed)
    log_event(
        "voice.transcript.metrics",
        language=getattr(info, "language", language),
        language_probability=getattr(info, "language_probability", None),
        avg_logprob=round(avg_logprob, 4),
        no_speech_prob=round(no_speech_prob, 4),
        duration_seconds=round(duration, 3),
    )
    return SpeechResult(text=text, avg_logprob=avg_logprob, no_speech_prob=no_speech_prob, duration_seconds=duration)


def feedback_sound(kind: str, enabled: bool) -> None:
    if not enabled or sys.platform != "win32":
        return

    def play() -> None:
        try:
            import winsound

            sound = winsound.MB_OK if kind == "accepted" else winsound.MB_ICONHAND
            winsound.MessageBeep(sound)
        except Exception:
            return

    threading.Thread(target=play, name=f"djgoo-feedback-{kind}", daemon=True).start()


def run(project_root: Path) -> None:
    secrets = load_project_secrets(project_root)
    voice_config = secrets.get("voice", {})
    settings = voice_settings(voice_config, project_root)
    input_device = resolve_input_device(settings["input_device"])
    corrections = load_corrections(project_root, settings["corrections"])
    dynamic_hotwords = " ".join(
        part for part in (settings["hotwords"], correction_hotwords(corrections)) if part.strip()
    )

    log_event(
        "voice.listener.starting",
        model=settings["model_name"],
        device=settings["device"],
        compute_type=settings["compute_type"],
        hotkey=settings["hotkey"],
        push_to_talk=settings["push_to_talk"],
        require_wake_word=settings["require_wake_word"],
        queue_path=str(settings["queue_path"]),
        input_device=input_device_summary(input_device),
        correction_count=len(corrections),
        vad_filter=settings["vad_filter"],
    )

    print(
        f"Loading Whisper model {settings['model_name']} "
        f"({settings['device']}/{settings['compute_type']})...",
        flush=True,
    )
    model_kwargs = {
        "device": settings["device"],
        "compute_type": settings["compute_type"],
    }
    if settings["cpu_threads"] > 0:
        model_kwargs["cpu_threads"] = settings["cpu_threads"]
    model = WhisperModel(settings["model_name"], **model_kwargs)

    hotkey_waiter = HotkeyWaiter(
        settings["hotkey"],
        poll_seconds=settings["hotkey_poll_seconds"],
    ) if settings["push_to_talk"] else None

    with PushToTalkAudioCapture(
        device=input_device,
        block_seconds=settings["block_seconds"],
        preroll_seconds=settings["preroll_seconds"],
        release_tail_seconds=settings["release_tail_seconds"],
    ) as capture:
        ready_message = (
            f"DjGoo voice is ready. Hold {settings['hotkey']} while speaking."
            if hotkey_waiter is not None
            else "DjGoo voice is ready."
        )
        print(ready_message, flush=True)
        log_event(
            "voice.listener.ready",
            message=ready_message,
            sample_rate=capture.sample_rate,
            block_seconds=capture.block_seconds,
        )

        while True:
            if hotkey_waiter is not None:
                hotkey_waiter.wait_for_press()
                log_event("voice.hotkey.detected", hotkey=settings["hotkey"])
                raw_audio = hotkey_waiter.capture_while_held(
                    capture,
                    min_seconds=settings["min_record_seconds"],
                    max_seconds=settings["max_record_seconds"],
                )
                mode = "hotkey"
            else:
                raw_audio = capture.record_for(settings["chunk_seconds"])
                mode = "continuous"

            audio = prepare_for_whisper(raw_audio, capture.sample_rate)
            metrics = audio_metrics(audio, 16_000)
            log_event(
                "voice.audio.recorded",
                mode=mode,
                seconds=round(metrics.seconds, 3),
                rms=round(metrics.rms, 6),
                peak=round(metrics.peak, 6),
                stream_status=capture.last_status,
            )
            if metrics.rms < settings["silence_rms_threshold"]:
                log_event(
                    "voice.audio.too_quiet",
                    rms=round(metrics.rms, 6),
                    threshold=settings["silence_rms_threshold"],
                )
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            result = transcribe(
                model,
                audio,
                language=settings["language"],
                beam_size=settings["beam_size"],
                hotwords=dynamic_hotwords,
                initial_prompt=settings["initial_prompt"],
                vad_filter=settings["vad_filter"],
                vad_min_silence_ms=settings["vad_min_silence_ms"],
                vad_speech_pad_ms=settings["vad_speech_pad_ms"],
            )
            if not result.text:
                log_event("voice.transcript.empty")
                feedback_sound("rejected", settings["feedback_beeps"])
                continue
            if result.avg_logprob < settings["min_avg_logprob"] or result.no_speech_prob > settings["max_no_speech_prob"]:
                log_event(
                    "voice.transcript.rejected",
                    transcript=result.text,
                    avg_logprob=result.avg_logprob,
                    no_speech_prob=result.no_speech_prob,
                    min_avg_logprob=settings["min_avg_logprob"],
                    max_no_speech_prob=settings["max_no_speech_prob"],
                )
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            transcript = apply_corrections(result.text, corrections)
            if transcript != result.text:
                log_event("voice.transcript.corrected", original=result.text, corrected=transcript)
            print(f"Heard: {transcript}", flush=True)
            log_event(
                "voice.transcript.heard",
                transcript=transcript,
                raw_transcript=result.text,
                confidence=round(math.exp(min(0.0, result.avg_logprob)), 4),
            )

            command = parse_command(transcript, require_wake=settings["require_wake_word"])
            log_event(
                "voice.command.parsed",
                intent=command.intent,
                query=command.query,
                playlist=command.playlist,
                value=command.value,
                confidence=command.confidence,
                raw=command.raw,
            )
            if command.intent in {"ignore", "unknown"}:
                log_event("voice.command.ignored", intent=command.intent, transcript=transcript)
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            append_queue_item(settings["queue_path"], command_to_queue_item(command, transcript=transcript))
            log_event("voice.queue.appended", type="command", intent=command.intent, query=command.query)
            feedback_sound("accepted", settings["feedback_beeps"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local DjGoo voice listener.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="DjGoo project root.",
    )
    args = parser.parse_args()

    try:
        run(Path(args.project_root).resolve())
    except KeyboardInterrupt:
        print("DjGoo local voice listener stopped.")
        log_event("voice.listener.stopped")
        return 0
    except Exception as exc:
        print(f"DjGoo local voice listener crashed: {exc!r}", file=sys.stderr, flush=True)
        log_event("voice.listener.crashed", error=type(exc).__name__, detail=str(exc))
        raise
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
