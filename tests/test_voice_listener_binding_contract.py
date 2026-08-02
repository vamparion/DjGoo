from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_original_listener_uses_generalized_binding_backend() -> None:
    source = (ROOT / "voice" / "djgoo_voice_listener.py").read_text(
        encoding="utf-8"
    )

    assert "from voice.input_binding import ButtonWaiter, COMMON_BUTTONS, is_button_down" in source
    assert "HOTKEYS = dict(COMMON_BUTTONS)" in source
    assert "HotkeyWaiter = ButtonWaiter" in source
    assert "return is_button_down(hotkey)" in source


def test_bound_listener_keeps_the_same_shared_backend() -> None:
    source = (ROOT / "voice" / "djgoo_voice_listener_bound.py").read_text(
        encoding="utf-8"
    )

    assert "listener.HOTKEYS = dict(COMMON_BUTTONS)" in source
    assert "listener.HotkeyWaiter = ButtonWaiter" in source
    assert "listener.is_hotkey_down = is_button_down" in source
