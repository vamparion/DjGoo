from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable


COMMON_BUTTONS: dict[str, int] = {
    "MOUSE1": 0x01,
    "MOUSE2": 0x02,
    "MOUSE3": 0x04,
    "MOUSE4": 0x05,
    "MOUSE5": 0x06,
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "ALT": 0x12,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESC": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PRINTSCREEN": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "NUMLOCK": 0x90,
    "SCROLLLOCK": 0x91,
    "VOLUME_MUTE": 0xAD,
    "VOLUME_DOWN": 0xAE,
    "VOLUME_UP": 0xAF,
    "MEDIA_NEXT": 0xB0,
    "MEDIA_PREVIOUS": 0xB1,
    "MEDIA_STOP": 0xB2,
    "MEDIA_PLAY_PAUSE": 0xB3,
}
for character in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    COMMON_BUTTONS[character] = ord(character)
for number in range(10):
    COMMON_BUTTONS[f"NUMPAD{number}"] = 0x60 + number
for number in range(1, 25):
    COMMON_BUTTONS[f"F{number}"] = 0x6F + number

CODE_TO_NAME = {code: name for name, code in COMMON_BUTTONS.items()}

if os.name == "nt":
    ctypes.windll.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    ctypes.windll.user32.GetAsyncKeyState.restype = ctypes.c_short


def normalize_button_name(value: str) -> str:
    text = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "LEFT_MOUSE": "MOUSE1",
        "RIGHT_MOUSE": "MOUSE2",
        "MIDDLE_MOUSE": "MOUSE3",
        "XBUTTON1": "MOUSE4",
        "XBUTTON2": "MOUSE5",
        "CONTROL": "CTRL",
        "ESCAPE": "ESC",
        "RETURN": "ENTER",
        "PRTSC": "PRINTSCREEN",
    }
    return aliases.get(text, text)


def button_code(value: str) -> int:
    name = normalize_button_name(value)
    code = COMMON_BUTTONS.get(name)
    if code is not None:
        return code
    if name.startswith("VK_"):
        try:
            code = int(name[3:], 16)
        except ValueError as exc:
            raise ValueError(f"Unsupported push-to-talk button: {value}") from exc
        if 1 <= code <= 0xFE:
            return code
    raise ValueError(f"Unsupported push-to-talk button: {value}")


def button_name(code: int) -> str:
    return CODE_TO_NAME.get(int(code), f"VK_{int(code):02X}")


def is_button_down(value: str, state_reader: Callable[[int], bool] | None = None) -> bool:
    code = button_code(value)
    if state_reader is not None:
        return bool(state_reader(code))
    if os.name != "nt":
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)


def _default_state_reader(code: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)


def capture_next_button(
    *,
    timeout: float = 12.0,
    poll_seconds: float = 0.01,
    release_stable_seconds: float = 0.15,
    state_reader: Callable[[int], bool] | None = None,
) -> str:
    """Return the next Windows keyboard or mouse button pressed.

    The initial click on the Bind button is ignored by first waiting until every
    button has been released for a short stable interval.
    """

    if state_reader is None:
        if os.name != "nt":
            raise RuntimeError("Automatic button capture is available on Windows")
        state_reader = _default_state_reader

    deadline = time.monotonic() + max(0.5, float(timeout))
    released_since: float | None = None
    while time.monotonic() < deadline:
        any_down = any(state_reader(code) for code in range(1, 0xFF))
        now = time.monotonic()
        if any_down:
            released_since = None
        elif released_since is None:
            released_since = now
        elif now - released_since >= release_stable_seconds:
            break
        time.sleep(max(0.005, poll_seconds))
    else:
        raise TimeoutError("No button was released before binding timed out")

    while time.monotonic() < deadline:
        for code in range(1, 0xFF):
            if state_reader(code):
                return button_name(code)
        time.sleep(max(0.005, poll_seconds))
    raise TimeoutError("No keyboard or mouse button was pressed")


class ButtonWaiter:
    def __init__(self, hotkey: str, *, poll_seconds: float) -> None:
        self.hotkey = normalize_button_name(hotkey)
        self.code = button_code(self.hotkey)
        self.poll_seconds = max(0.005, float(poll_seconds))

    @property
    def mode(self) -> str:
        return "GetAsyncKeyState keyboard/mouse hold-to-talk"

    def wait_for_press(self, *, heartbeat_seconds: float = 30.0) -> None:
        from voice.operational_log import log_event

        last_heartbeat = time.monotonic()
        while not is_button_down(self.hotkey):
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                log_event("voice.hotkey.waiting", hotkey=self.hotkey, mode=self.mode)
                last_heartbeat = now
            time.sleep(self.poll_seconds)

    def capture_while_held(self, capture, *, min_seconds: float, max_seconds: float):
        capture.begin()
        started = time.monotonic()
        while is_button_down(self.hotkey) and time.monotonic() - started < max_seconds:
            time.sleep(self.poll_seconds)
        while time.monotonic() - started < min_seconds:
            time.sleep(self.poll_seconds)
        audio = capture.finish()
        while is_button_down(self.hotkey):
            time.sleep(self.poll_seconds)
        return audio
