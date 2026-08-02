from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from local_cogs.djgoowelcome.relay_cog import DjGooRelay


def _relay(path: Path) -> DjGooRelay:
    relay = DjGooRelay.__new__(DjGooRelay)
    relay.djgoo_cog = SimpleNamespace(_secrets_path=lambda: path)
    return relay


def test_relay_settings_are_not_discarded(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(
        json.dumps(
            {
                "token": "preserved",
                "voice_gateway": {
                    "relay": {
                        "enabled": True,
                        "url": "wss://relay.example.test",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert _relay(path)._settings() == {
        "enabled": True,
        "url": "wss://relay.example.test",
    }


def test_saving_discord_bridge_preserves_existing_secrets(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(
        json.dumps(
            {
                "token": "preserved",
                "voice": {"hotkey": "F12"},
                "voice_gateway": {"port": 47632},
            }
        ),
        encoding="utf-8",
    )
    webhook = (
        "https://discord.com/api/"
        + "webhooks/123456789012345678/"
        + "test-token-value"
    )

    relay = _relay(path)
    relay._save_discord_webhook_url(webhook)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["token"] == "preserved"
    assert saved["voice"] == {"hotkey": "F12"}
    assert saved["voice_gateway"]["port"] == 47632
    assert saved["voice_gateway"]["discord_relay"] == {
        "enabled": True,
        "webhook_url": webhook,
    }
