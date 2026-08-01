from __future__ import annotations

from dataclasses import dataclass

from tools.input_binding_adapter import install_input_binding


@dataclass(frozen=True)
class Spec:
    name: str
    command: list[str]
    command_markers: tuple[str, ...]


class Core:
    @staticmethod
    def build_specs():
        return [
            Spec(
                name="voice",
                command=["python", "-m", "voice.djgoo_voice_listener"],
                command_markers=("voice.djgoo_voice_listener", "root"),
            ),
            Spec(name="redbot", command=["python", "bot"], command_markers=("bot",)),
        ]


def test_adapter_only_replaces_voice_listener_entrypoint() -> None:
    core = Core()
    install_input_binding(core)
    voice, redbot = core.build_specs()
    assert "voice.djgoo_voice_listener_bound" in voice.command
    assert voice.command_markers[0] == "voice.djgoo_voice_listener_bound"
    assert redbot.command == ["python", "bot"]
