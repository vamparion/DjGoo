from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import aiohttp
from redbot.core import commands

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice.command_queue import drain_queue

from .audio_bridge import DjGooAudioBridge
from .helpers import (
    build_voice_command_payload,
    build_welcome_payload,
    load_secrets,
    should_send_welcome,
)


log = logging.getLogger("red.djgoowelcome")


class DjGooWelcome(commands.Cog):
    """Posts a DjGoo command welcome screen when humans join voice."""

    def __init__(self, bot):
        self.bot = bot
        self._last_sent: Dict[Tuple[int, int], float] = {}
        self._cooldown_seconds = 300
        self._audio_bridge = DjGooAudioBridge(
            bot=self.bot,
            project_root=PROJECT_ROOT,
            send_payload=self._send_webhook_payload,
        )
        self._queue_task = self.bot.loop.create_task(self._command_queue_loop())

    def cog_unload(self):
        self._queue_task.cancel()

    async def red_delete_data_for_user(self, **kwargs):
        return

    def _secrets_path(self) -> Path:
        configured = os.environ.get("DJGOO_SECRETS_FILE")
        if configured:
            return Path(configured)
        return Path.cwd() / "config" / "secrets.json"

    def _cooldown_key(self, member, channel) -> Tuple[int, int]:
        return (int(member.id), int(channel.id))

    def _queue_path(self) -> Path:
        secrets = load_secrets(self._secrets_path())
        configured = secrets.get("voice", {}).get("queue_path", "")
        if configured:
            return Path(configured)
        return Path.cwd() / "data" / "voice-command-queue.jsonl"

    def _is_on_cooldown(self, member, channel) -> bool:
        key = self._cooldown_key(member, channel)
        now = time.monotonic()
        last_sent = self._last_sent.get(key, 0.0)
        if now - last_sent < self._cooldown_seconds:
            return True
        self._last_sent[key] = now
        return False

    async def _send_webhook_payload(self, payload: Dict[str, Any]) -> None:
        secrets = load_secrets(self._secrets_path())
        webhook_url = secrets["webhook_url"]
        if not webhook_url:
            log.warning("DjGoo webhook is not configured. Edit config/secrets.json.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as response:
                    if response.status >= 400:
                        body = await response.text()
                        log.warning(
                            "DjGoo webhook failed with HTTP %s: %s",
                            response.status,
                            body[:500],
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("DjGoo webhook request failed.")

    async def _command_queue_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        while True:
            try:
                for item in drain_queue(self._queue_path()):
                    await self._send_webhook_payload(build_voice_command_payload(item))
                    await self._audio_bridge.handle(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("DjGoo voice command queue loop failed.")
            await asyncio.sleep(1)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not should_send_welcome(member, before, after):
            return

        channel = after.channel
        if self._is_on_cooldown(member, channel):
            return

        payload = build_welcome_payload(member.display_name, channel.name)
        await self._send_webhook_payload(payload)
