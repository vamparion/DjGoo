from __future__ import annotations

from voice import djgoo_voice_listener as listener
from voice.input_binding import ButtonWaiter, COMMON_BUTTONS, is_button_down


# Keep the established listener implementation and replace only its limited
# F10/F11/F12 input backend with the shared Windows keyboard/mouse backend.
listener.HOTKEYS = dict(COMMON_BUTTONS)
listener.HotkeyWaiter = ButtonWaiter
listener.is_hotkey_down = is_button_down


def main() -> int:
    return int(listener.main())


if __name__ == "__main__":
    raise SystemExit(main())
