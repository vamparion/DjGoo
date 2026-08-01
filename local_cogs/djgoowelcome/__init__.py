from pathlib import Path

from redbot.core.bot import Red

from . import djgoowelcome as cog_module
from .relay_cog import DjGooRelay
from .remote_aware_bridge import RemoteAwareDjGooAudioBridge

# Select the requester-aware bridge at the package boundary while retaining one
# Red Audio/Lavalink playback authority.
cog_module.EnhancedDjGooAudioBridge = RemoteAwareDjGooAudioBridge
DjGooWelcome = cog_module.DjGooWelcome
PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def setup(bot: Red) -> None:
    djgoo = DjGooWelcome(bot)
    await bot.add_cog(djgoo)
    await bot.add_cog(DjGooRelay(bot, djgoo, PROJECT_ROOT))
