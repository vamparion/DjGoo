from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

try:
    import keyboard as keyboard_backend
except Exception:
    keyboard_backend = None

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
KEYBOARD_BACKEND_NAMES = {
    "F10": "f10",
    "F11": "f11",
    "F12": "f12",
}
WM_HOTKEY = 0x0312
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
PM_REMOVE = 0x0001
MOD_NOREPEAT = 0x4000
WH_KEYBOARD_LL = 13

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    ctypes.c_size_t,
    ctypes.c_void_p,
)

if sys.platform == "win32":
    ctypes.windll.user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    ctypes.windll.user32.RegisterHotKey.restype = ctypes.c_bool
    ctypes.windll.user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    ctypes.windll.user32.UnregisterHotKey.restype = ctypes.c_bool
    ctypes.windll.user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        LowLevelKeyboardProc,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    ctypes.windll.user32.SetWindowsHookExW.restype = ctypes.c_void_p
    ctypes.windll.user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    ctypes.windll.user32.UnhookWindowsHookEx.restype = ctypes.c_bool
    ctypes.windll.user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p]
    ctypes.windll.user32.CallNextHookEx.restype = ctypes.c_ssize_t
    ctypes.windll.user32.PeekMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    ctypes.windll.user32.PeekMessageW.restype = ctypes.c_bool
    ctypes.windll.kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    ctypes.windll.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    ctypes.windll.kernel32.GetLastError.restype = ctypes.c_uint


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", ctypes.c_long * 2),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint),
        ("scanCode", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HotkeyWaiter:
    def __init__(self, hotkey: str):
        self.hotkey = hotkey.upper()
        self.vk_code = HOTKEYS.get(self.hotkey)
        self.keyboard_name = KEYBOARD_BACKEND_NAMES.get(self.hotkey, self.hotkey.lower())
        self.hotkey_id = 0xD600
        self.registered = False
        self.hook_handle = None
        self._hook_hit = False
        self._hook_callback = None
        self._keyboard_backend_failed = False
        if sys.platform == "win32" and self.vk_code is not None:
            self.registered = bool(
                ctypes.windll.user32.RegisterHotKey(None, self.hotkey_id, MOD_NOREPEAT, self.vk_code)
            )
            if not self.registered:
                self._install_keyboard_hook()
        log_event(
            "voice.hotkey.registration",
            hotkey=self.hotkey,
            registered=self.registered,
            hook_installed=bool(self.hook_handle),
            keyboard_backend=bool(keyboard_backend),
            mode=self.mode,
        )

    def close(self) -> None:
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.hotkey_id)
            self.registered = False
        if self.hook_handle:
            ctypes.windll.user32.UnhookWindowsHookEx(self.hook_handle)
            self.hook_handle = None

    @property
    def mode(self) -> str:
        if self.registered:
            return "RegisterHotKey"
        if self.hook_handle:
            return "low-level keyboard hook"
        return "GetAsyncKeyState fallback"

    def wait(
        self,
        *,
        heartbeat_seconds: float = 30.0,
        poll_seconds: float = 0.03,
        timeout_seconds: float | None = None,
    ) -> bool:
        last_heartbeat = time.monotonic()
        started = last_heartbeat
        while True:
            if self._consume_hotkey_message():
                return True
            if self._hook_hit:
                self._hook_hit = False
                return True
            if is_hotkey_down(self.hotkey):
                return True
            if self._is_keyboard_backend_pressed():
                return True
            now = time.monotonic()
            if timeout_seconds is not None and now - started >= timeout_seconds:
                return False
            if now - last_heartbeat >= heartbeat_seconds:
                log_event(
                    "voice.hotkey.waiting",
                    hotkey=self.hotkey,
                    registered=self.registered,
                    hook_installed=bool(self.hook_handle),
                    keyboard_backend=bool(keyboard_backend) and not self._keyboard_backend_failed,
                    mode=self.mode,
                )
                last_heartbeat = now
            time.sleep(poll_seconds)

    def _consume_hotkey_message(self) -> bool:
        msg = MSG()
        while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_HOTKEY and int(msg.wParam) == self.hotkey_id:
                return True
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        return False

    def _is_keyboard_backend_pressed(self) -> bool:
        if keyboard_backend is None or self._keyboard_backend_failed:
            return False
        try:
            return bool(keyboard_backend.is_pressed(self.keyboard_name))
        except Exception as exc:
            self._keyboard_backend_failed = True
            log_event(
                "voice.hotkey.keyboard_backend_failed",
                hotkey=self.hotkey,
                error=type(exc).__name__,
                detail=str(exc),
            )
            return False

    def _install_keyboard_hook(self) -> None:
        if self.vk_code is None:
            return

        def callback(n_code, w_param, l_param):
            if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if int(data.vkCode) == int(self.vk_code):
                    self._hook_hit = True
            return ctypes.windll.user32.CallNextHookEx(self.hook_handle, n_code, w_param, l_param)

        self._hook_callback = LowLevelKeyboardProc(callback)
        module_handle = ctypes.windll.kernel32.GetModuleHandleW(None)
        self.hook_handle = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_callback,
            module_handle,
            0,
        )
        if not self.hook_handle:
            log_event(
                "voice.hotkey.hook_failed",
                hotkey=self.hotkey,
                error_code=ctypes.windll.kernel32.GetLastError(),
            )
            self._hook_callback = None


def record_chunk(seconds: float, *, device: int | str | None = None) -> np.ndarray:
    frames = int(SAMPLE_RATE * seconds)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device)
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
    block_frames = max(1, int(SAMPLE_RATE * block_seconds))
    max_frames = int(SAMPLE_RATE * max_seconds)
    min_frames = int(SAMPLE_RATE * min_seconds)
    chunks = []
    total_frames = 0
    while total_frames < max_frames:
        data = sd.rec(block_frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device)
        sd.wait()
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
                    hint="Tap the hotkey, release it, then speak toward the selected microphone.",
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
