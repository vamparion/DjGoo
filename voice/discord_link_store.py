from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from voice.secure_store import load_protected_json, save_protected_json


class DiscordLinkStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = load_protected_json(self.path)
        except (OSError, ValueError, RuntimeError):
            return {}
        routes = payload.get("routes", {}) if isinstance(payload, dict) else {}
        return routes if isinstance(routes, dict) else {}

    def get_for_guild(self, guild_id: int) -> dict[str, Any] | None:
        with self._lock:
            route = self._read().get(str(int(guild_id)))
        return dict(route) if isinstance(route, dict) else None

    def get_for_webhook(self, webhook_id: int) -> dict[str, Any] | None:
        target = str(int(webhook_id))
        with self._lock:
            for guild_id, route in self._read().items():
                if not isinstance(route, dict):
                    continue
                if str(route.get("webhook_id") or "") == target:
                    return {"guild_id": int(guild_id), **route}
        return None

    def set(
        self,
        guild_id: int,
        *,
        channel_id: int,
        webhook_id: int,
        webhook_url: str,
    ) -> None:
        parsed = urlparse(webhook_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Discord Link webhook URL must use HTTPS")
        with self._lock:
            routes = self._read()
            routes[str(int(guild_id))] = {
                "channel_id": int(channel_id),
                "webhook_id": int(webhook_id),
                "webhook_url": webhook_url,
            }
            save_protected_json(
                self.path,
                {"schema": 1, "routes": routes},
            )

    def clear(self, guild_id: int) -> None:
        with self._lock:
            routes = self._read()
            routes.pop(str(int(guild_id)), None)
            save_protected_json(
                self.path,
                {"schema": 1, "routes": routes},
            )
