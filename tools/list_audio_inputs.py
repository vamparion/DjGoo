from __future__ import annotations

import json
import time

import sounddevice as sd


def main() -> int:
    default = sd.default.device
    default_input = list(default)[0] if not isinstance(default, int) else default
    by_name: dict[str, dict[str, object]] = {}
    for index, item in enumerate(sd.query_devices()):
        if int(item.get("max_input_channels", 0) or 0) <= 0:
            continue
        available = False
        error = ""
        try:
            stream = sd.InputStream(device=index, channels=1, dtype="float32", callback=lambda *_args: None)
            stream.start(); time.sleep(0.03); stream.stop(); stream.close()
            available = True
        except Exception as exc:
            error = str(exc)
        candidate = {
            "id": index,
            "name": str(item.get("name") or f"Input {index}"),
            "available": available,
            "default": index == default_input,
            "error": error,
        }
        name = str(candidate["name"])
        existing = by_name.get(name)
        if existing is None or (available and not bool(existing["available"])):
            by_name[name] = candidate
        elif index == default_input:
            existing["default"] = True
    devices = list(by_name.values())
    print(json.dumps({"devices": devices, "default_id": default_input}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
