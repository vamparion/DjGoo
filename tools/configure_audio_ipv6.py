import json
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "data" / "discordbot" / "cogs" / "Audio" / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    global_config = data.setdefault("2711759130", {}).setdefault("GLOBAL", {})
    global_config.update(
        {
            "use_external_lavalink": True,
            "host": "[::1]",
            "rest_port": 2333,
            "ws_port": 2333,
            "password": "youshallnotpass",
            "secured_ws": False,
            "yaml__server__address": "::1",
        }
    )
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
