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
from voice.command_parser import PendingChoice, parse_command, parse_emergency_control, parse_followup
from voice.listener_settings import voice_settings
from voice.operational_log import log_event
from voice.secrets import load_project_secrets


SAMPLE_RATE = 16000
HOTKEYS = {
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

if sys.platform == "win32":
    ctypes.windll.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    ctypes.windll.user32.GetAsyncKeyState.restype = ctypes.c_short


class HotkeyWaiter:
    def __init__(self, hotkey: str):
        self.hotkey = hotkey.upper()
        self.vk_code = HOTKEYS.get(self.hotkey)
        log_event(
            "voice.hotkey.registration",
            hotkey=self.hotkey,
            mode=self.mode,
        )

    def close(self) -> None:
        return None

    @property
    def mode(self) -> str:
        return "GetAsyncKeyState hold-to-talk"

    def wait(
        self,
        *,
        heartbeat_seconds: float = 30.0,
        poll_seconds: float = 0.05,
        timeout_seconds: float | None = None,
    ) -> bool:
        last_heartbeat = time.monotonic()
        started = last_heartbeat
        while True:
            if is_hotkey_down(self.hotkey):
                return True
            now = time.monotonic()
            if timeout_seconds is not None and now - started >= timeout_seconds:
                return False
            if now - last_heartbeat >= heartbeat_seconds:
                log_event(
                    "voice.hotkey.waiting",
                    hotkey=self.hotkey,
                    mode=self.mode,
                )
                last_heartbeat = now
            time.sleep(poll_seconds)


def record_chunk(seconds: float, *, device: int | str | None = None) -> np.ndarray:
    samplerate = input_device_samplerate(device)
    frames = int(samplerate * seconds)
    audio = sd.rec(frames, samplerate=samplerate, channels=1, dtype="float32", device=device)
    sd.wait()
    return resample_to_whisper_rate(audio.reshape(-1), samplerate)


def input_device_samplerate(device: int | str | None) -> int:
    try:
        info = sd.query_devices(device, "input")
        return int(float(info.get("default_samplerate") or SAMPLE_RATE))
    except Exception:
        return SAMPLE_RATE


def resample_to_whisper_rate(audio: np.ndarray, samplerate: int) -> np.ndarray:
    if samplerate == SAMPLE_RATE or audio.size == 0:
        return audio.astype("float32", copy=False)
    target_size = max(1, int(audio.size * SAMPLE_RATE / samplerate))
    original = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    target = np.linspace(0.0, 1.0, num=target_size, endpoint=False)
    return np.interp(target, original, audio).astype("float32")


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


def wait_for_hotkey_release(hotkey: str, *, poll_seconds: float = 0.03) -> None:
    while is_hotkey_down(hotkey):
        time.sleep(poll_seconds)


def audio_rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def resolve_input_device(configured: object) -> int | str | None:
    if configured is None or str(configured).strip() == "":
        return None
    if isinstance(configured, int):
        return configured
    text = str(configured).strip()
    if text.isdigit():
        return int(text)
    lowered = text.lower()
    matches = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        if lowered in str(device.get("name", "")).lower():
            matches.append(index)
    if matches:
        return matches[0]
    return text


def input_device_summary(device: int | str | None) -> dict:
    try:
        try:
            default_input = list(sd.default.device)[0]
        except TypeError:
            default_input = sd.default.device
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


def record_hotkey_command(
    hotkey: str,
    *,
    min_seconds: float,
    tap_seconds: float,
    max_seconds: float,
    device: int | str | None = None,
    block_seconds: float = 0.1,
) -> np.ndarray:
    samplerate = input_device_samplerate(device)
    block_frames = max(1, int(samplerate * block_seconds))
    max_frames = int(samplerate * max_seconds)
    min_frames = int(samplerate * min_seconds)
    tap_frames = int(samplerate * min(max_seconds, tap_seconds))
    chunks = []
    total_frames = 0
    was_held_after_minimum = False
    while total_frames < max_frames:
        data = sd.rec(block_frames, samplerate=samplerate, channels=1, dtype="float32", device=device)
        sd.wait()
        chunks.append(data.reshape(-1).copy())
        total_frames += len(chunks[-1])

        if total_frames >= min_frames and is_hotkey_down(hotkey):
            was_held_after_minimum = True
        if total_frames >= min_frames and not is_hotkey_down(hotkey) and was_held_after_minimum:
            break
        if total_frames >= tap_frames and not is_hotkey_down(hotkey):
            break
    if not chunks:
        return np.array([], dtype="float32")
    return resample_to_whisper_rate(np.concatenate(chunks), samplerate)


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
        vad_filter=False,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt or None,
        hotwords=hotwords or None,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def run(project_root: Path) -> None:
    secrets = load_project_secrets(project_root)
    voice_config = secrets.get("voice", {})
    settings = voice_settings(voice_config, project_root)
    input_device = resolve_input_device(settings["input_device"])
    log_event(
        "voice.listener.starting",
        model=settings["model_name"],
        compute_type=settings["compute_type"],
        hotkey=settings["hotkey"],
        push_to_talk=settings["push_to_talk"],
        require_wake_word=settings["require_wake_word"],
        queue_path=str(settings["queue_path"]),
        silence_rms_threshold=settings["silence_rms_threshold"],
        input_device=input_device_summary(input_device),
        emergency_voice_controls=settings["emergency_voice_controls"],
    )

    print(f"Loading Whisper model {settings['model_name']} ({settings['compute_type']})...", flush=True)
    model = WhisperModel(settings["model_name"], device="cpu", compute_type=settings["compute_type"])
    if settings["push_to_talk"]:
        ready_message = f"DjGoo local voice listener is running. Hold {settings['hotkey']} while speaking."
    else:
        ready_message = "DjGoo local voice listener is running. Say 'DjGoo ...' into the default mic."
    print(ready_message, flush=True)
    log_event("voice.listener.ready", message=ready_message)

    pending: PendingChoice | None = None
    hotkey_waiter = HotkeyWaiter(settings["hotkey"]) if settings["push_to_talk"] else None
    last_silence_log = 0.0
    try:
        while True:
            recording_mode = "continuous"
            if settings["push_to_talk"]:
                hotkey_detected = hotkey_waiter.wait(
                    timeout_seconds=(
                        settings["emergency_listen_interval_seconds"]
                        if settings["emergency_voice_controls"]
                        else None
                    )
                )
                if hotkey_detected:
                    recording_mode = "hotkey"
                    print(
                        f"Hotkey {settings['hotkey']} detected. Recording while held...",
                        flush=True,
                    )
                    log_event(
                        "voice.hotkey.detected",
                        hotkey=settings["hotkey"],
                        record_mode="hold_to_talk",
                        max_seconds=settings["max_record_seconds"],
                    )
                    audio = record_hotkey_command(
                        settings["hotkey"],
                        min_seconds=settings["min_record_seconds"],
                        tap_seconds=settings["tap_record_seconds"],
                        max_seconds=settings["max_record_seconds"],
                        device=input_device,
                    )
                    wait_for_hotkey_release(settings["hotkey"])
                else:
                    recording_mode = "emergency"
                    audio = record_chunk(settings["emergency_chunk_seconds"], device=input_device)
            else:
                audio = record_chunk(settings["chunk_seconds"], device=input_device)
            duration = audio.size / SAMPLE_RATE if audio.size else 0.0
            rms = audio_rms(audio)
            print(f"Recorded {duration:.1f}s, mic level {rms:.4f}.", flush=True)
            log_event(
                "voice.audio.recorded",
                seconds=round(duration, 2),
                rms=round(rms, 6),
                mode=recording_mode,
            )
            if recording_mode == "hotkey" and rms < settings["silence_rms_threshold"]:
                log_event(
                    "voice.audio.too_quiet",
                    rms=round(rms, 6),
                    threshold=settings["silence_rms_threshold"],
                    hint="Hold the hotkey while speaking toward the selected microphone.",
                )
                print("Recorded audio was too quiet; skipping transcription.", flush=True)
                continue
            if recording_mode in {"continuous", "emergency"} and rms < settings["silence_rms_threshold"]:
                now = time.monotonic()
                if now - last_silence_log >= 30.0:
                    log_event(
                        "voice.audio.silence",
                        rms=round(rms, 6),
                        threshold=settings["silence_rms_threshold"],
                    )
                    last_silence_log = now
                continue
            transcript = transcribe(
                model,
                audio,
                language=settings["language"],
                beam_size=settings["beam_size"],
                hotwords=settings["hotwords"],
                initial_prompt=settings["initial_prompt"],
            )
            if not transcript:
                print("No speech recognized.", flush=True)
                log_event("voice.transcript.empty")
                continue

            print(f"Heard: {transcript}", flush=True)
            log_event("voice.transcript.heard", transcript=transcript)
            now = time.monotonic()
            if pending is not None:
                followup = parse_followup(transcript, pending, now=now)
                log_event("voice.followup.parsed", action=followup.action, index=followup.index, raw=followup.raw)
                if followup.action == "expired":
                    append_queue_item(settings["queue_path"], followup_to_queue_item(followup, transcript=transcript))
                    log_event("voice.queue.appended", type="followup", action=followup.action)
                    pending = None
                    continue
                if followup.action in {"choose", "neither", "cancel"}:
                    append_queue_item(settings["queue_path"], followup_to_queue_item(followup, transcript=transcript))
                    log_event("voice.queue.appended", type="followup", action=followup.action, index=followup.index)
                    pending = None
                    continue

            command = (
                parse_emergency_control(transcript)
                if recording_mode == "emergency"
                else parse_command(transcript, require_wake=settings["require_wake_word"])
            )
            log_event(
                "voice.command.parsed",
                mode=recording_mode,
                intent=command.intent,
                query=command.query,
                playlist=command.playlist,
                value=command.value,
                confidence=command.confidence,
                raw=command.raw,
            )
            if command.intent in {"ignore", "unknown"}:
                print(f"Ignored transcript as {command.intent}: {transcript}", flush=True)
                log_event("voice.command.ignored", intent=command.intent, transcript=transcript)
                continue

            append_queue_item(settings["queue_path"], command_to_queue_item(command, transcript=transcript))
            print(f"Queued command: {command.intent}", flush=True)
            log_event("voice.queue.appended", type="command", intent=command.intent, query=command.query)
    finally:
        if hotkey_waiter is not None:
            hotkey_waiter.close()


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
        log_event("voice.listener.stopped")
        return 0
    except Exception as exc:
        print(f"DjGoo local voice listener crashed: {exc!r}", file=sys.stderr, flush=True)
        log_event("voice.listener.crashed", error=type(exc).__name__, detail=str(exc))
        raise
    return 1


if __name__ == "__main__":
    sys.exit(main())
