from __future__ import annotations

import pytest

from voice.input_binding import button_code, button_name, normalize_button_name


def test_common_keyboard_and_mouse_buttons_are_supported() -> None:
    assert button_code("F12") == 0x7B
    assert button_code("mouse4") == 0x05
    assert button_code("A") == 0x41
    assert button_name(0x06) == "MOUSE5"


def test_generic_windows_virtual_key_round_trips() -> None:
    assert button_code("VK_E2") == 0xE2
    assert button_name(0xE2) == "VK_E2"


def test_button_aliases_are_normalized() -> None:
    assert normalize_button_name("left mouse") == "MOUSE1"
    assert normalize_button_name("escape") == "ESC"
    assert normalize_button_name("control") == "CTRL"


def test_unsupported_button_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        button_code("not-a-real-button")
