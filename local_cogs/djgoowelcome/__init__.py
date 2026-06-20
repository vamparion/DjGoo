from redbot.core.bot import Red

from .djgoowelcome import DjGooWelcome


async def setup(bot: Red) -> None:
    await bot.add_cog(DjGooWelcome(bot))
