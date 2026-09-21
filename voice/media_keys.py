from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from voice.gaming_session import GamingSessionStore
from voice.input_binding import is_button_down
from voice.operational_log import log_event


MEDIA_KEY_INTENTS = {
    "MEDIA_PLAY_PAUSE": "toggle_pause",
    "MEDIA_NEXT": "skip",
    "MEDIA_PREVIOUS": "replay",
    "VOLUME_MUTE": "mini_mute",
}


def start_media_key_listener(
    project_root: Path,
    emit: Callable[[str], None],
    *,
    poll_seconds: float = 0.04,
) -> threading.Thread:
    settings = GamingSessionStore(
        project_root / "data" / "djgoo-gaming-session.json"
    )

    def run() -> None:
        previous = {key: False for key in MEDIA_KEY_INTENTS}
        log_event("media_keys.started", keys=list(MEDIA_KEY_INTENTS))
        while True:
            enabled = bool(settings.settings(0)["media_keys_enabled"])
            for key, intent in MEDIA_KEY_INTENTS.items():
                down = is_button_down(key) if enabled else False
                if down and not previous[key]:
                    emit(intent)
                    log_event("media_keys.command", key=key, intent=intent)
                previous[key] = down
            time.sleep(max(0.02, poll_seconds))

    thread = threading.Thread(target=run, name="djgoo-media-keys", daemon=True)
    thread.start()
    return thread
