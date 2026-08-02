from __future__ import annotations

from dataclasses import replace


def install_input_binding(core) -> None:
    original_build_specs = core.build_specs

    def build_specs():
        specs = []
        for spec in original_build_specs():
            if spec.name != "voice":
                specs.append(spec)
                continue
            command = list(spec.command)
            try:
                module_index = command.index("voice.djgoo_voice_listener")
            except ValueError:
                specs.append(spec)
                continue
            command[module_index] = "voice.djgoo_voice_listener_bound"
            markers = tuple(
                "voice.djgoo_voice_listener_bound"
                if marker == "voice.djgoo_voice_listener"
                else marker
                for marker in spec.command_markers
            )
            specs.append(
                replace(
                    spec,
                    command=command,
                    command_markers=markers,
                )
            )
        return specs

    core.build_specs = build_specs
