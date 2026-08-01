from pathlib import Path

from redbot.core import commands
from redbot.core.bot import Red

from . import djgoowelcome as cog_module
from .guide_cog import DjGooGuide
from .relay_cog import DjGooRelay
from .remote_aware_bridge import RemoteAwareDjGooAudioBridge


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMED_REQUEST_INTENTS = {"play_now", "queue_request"}


# Select the complete DjGoo bridge at the package boundary while retaining one
# playback authority. Third-party engine names stay behind this internal seam.
cog_module.EnhancedDjGooAudioBridge = RemoteAwareDjGooAudioBridge
cog_module.JOINING_REMOTE_INTENTS.update(TIMED_REQUEST_INTENTS)
DjGooWelcome = cog_module.DjGooWelcome


def _install_timed_chat_routing() -> None:
    if bool(getattr(DjGooWelcome, "_djgoo_timed_chat_routing", False)):
        return
    original_on_message = DjGooWelcome.on_message

    @commands.Cog.listener()
    async def on_message(self, message) -> None:
        if (
            message.guild is not None
            and message.author != self.bot.user
            and not getattr(message.author, "bot", False)
        ):
            command_text = cog_module.parse_djgoo_chat_command(
                message.content
            )
            if command_text:
                parsed = cog_module.parse_command(message.content)
                if parsed.intent in TIMED_REQUEST_INTENTS:
                    result = await self._audio_bridge.handle(
                        cog_module.command_to_queue_item(
                            parsed,
                            transcript=message.content,
                            source="chat",
                        )
                    )
                    cog_module.log_event(
                        "chat.command.handled_by_bridge",
                        intent=parsed.intent,
                        result=result,
                    )
                    return
        await original_on_message(self, message)

    DjGooWelcome.on_message = on_message
    DjGooWelcome._djgoo_timed_chat_routing = True


_install_timed_chat_routing()


async def setup(bot: Red) -> None:
    djgoo = DjGooWelcome(bot)
    await bot.add_cog(djgoo)
    await bot.add_cog(DjGooGuide())
    await bot.add_cog(DjGooRelay(bot, djgoo, PROJECT_ROOT))
