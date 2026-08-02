from voice import djgoo_voice_listener as listener
from voice.input_binding import ButtonWaiter, COMMON_BUTTONS


def test_original_listener_accepts_generalized_host_binding() -> None:
    assert listener.HOTKEYS["F5"] == COMMON_BUTTONS["F5"]
    assert listener.HOTKEYS["MOUSE4"] == COMMON_BUTTONS["MOUSE4"]

    waiter = listener.HotkeyWaiter("F5", poll_seconds=0.01)

    assert isinstance(waiter, ButtonWaiter)
    assert waiter.hotkey == "F5"


def test_bound_listener_and_original_listener_share_the_same_backend() -> None:
    from voice import djgoo_voice_listener_bound as bound

    assert bound.listener.HotkeyWaiter is ButtonWaiter
    assert bound.listener.HOTKEYS["F5"] == COMMON_BUTTONS["F5"]
