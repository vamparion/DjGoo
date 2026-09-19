from launcher.djgoo_overlay import DjGooMiniPlayer


class Value:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_radio_button_starts_from_request_field_and_stops_active_station() -> None:
    player = DjGooMiniPlayer.__new__(DjGooMiniPlayer)
    player._payload = {}
    player.request = Value("80s")
    sent = []
    remembered = []
    player.send = lambda intent, **values: sent.append((intent, values))
    player._remember_search = remembered.append

    player._toggle_radio()

    assert sent[0][0] == "start_radio"
    assert sent[0][1]["query"] == "80s"
    assert player.request.get() == ""
    assert remembered == ["80s"]

    player._payload = {"station_details": {"name": "80s radio"}}
    player._toggle_radio()

    assert sent[1][0] == "mini_stop_radio"
