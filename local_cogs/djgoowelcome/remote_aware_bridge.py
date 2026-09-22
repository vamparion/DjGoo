from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict

from voice.operational_log import log_event

from .gaming_audio_bridge import GamingDjGooAudioBridge


_CURRENT_COMMAND: ContextVar[Dict[str, Any] | None] = ContextVar(
    "djgoo_current_command",
    default=None,
)


class RemoteAwareDjGooAudioBridge(GamingDjGooAudioBridge):
    """Resolve a recipient command to its paired Discord member."""

    async def handle(self, item: Dict[str, Any]) -> str:
        token = _CURRENT_COMMAND.set(item)
        is_mini = str(item.get("source") or "") == "mini_player"
        if is_mini:
            self._mini_command_depth = int(getattr(self, "_mini_command_depth", 0)) + 1
        try:
            return await super().handle(item)
        finally:
            if is_mini:
                self._mini_command_depth = max(
                    0,
                    int(getattr(self, "_mini_command_depth", 1)) - 1,
                )
            _CURRENT_COMMAND.reset(token)

    def _context(self):
        item = _CURRENT_COMMAND.get()
        if item and item.get("source") in {"voice_remote", "web_remote"}:
            try:
                guild_id = int(item.get("guild_id") or 0)
                user_id = int(item.get("user_id") or 0)
                expected_voice_channel_id = int(item.get("voice_channel_id") or 0)
            except (TypeError, ValueError):
                guild_id = user_id = expected_voice_channel_id = 0
            guild = self.bot.get_guild(guild_id) if guild_id else None
            member = guild.get_member(user_id) if guild is not None and user_id else None
            voice_channel = getattr(getattr(member, "voice", None), "channel", None)
            if (
                guild is not None
                and member is not None
                and voice_channel is not None
                and (
                    not expected_voice_channel_id
                    or int(voice_channel.id) == expected_voice_channel_id
                )
            ):
                channel = self._best_text_channel(guild)
                if channel is not None:
                    log_event(
                        "bridge.context.remote_member.selected",
                        guild_id=guild.id,
                        voice_channel_id=voice_channel.id,
                        member_id=member.id,
                        command_id=item.get("command_id"),
                        device_id=item.get("device_id"),
                    )
                    return self._context_for(guild, member, channel)
            log_event(
                "bridge.context.remote_member.unavailable",
                guild_id=guild_id,
                member_id=user_id,
                voice_channel_id=expected_voice_channel_id,
                command_id=item.get("command_id"),
            )
            return None
        return super()._context()
