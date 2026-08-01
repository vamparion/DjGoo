from __future__ import annotations

from voice import djgoo_voice_listener as listener
from voice.input_binding import ButtonWaiter, COMMON_BUTTONS, is_button_down


listener.HOTKEYS = dict(COMMON_BUTTONS)
listener.HotkeyWaiter = ButtonWaiter
listener.is_hotkey_down = is_button_down

from voice import djgoo_voice_remote as remote


def main() -> int:
    return int(remote.main())


if __name__ == "__main__":
    raise SystemExit(main())
