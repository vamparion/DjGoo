import asyncio
import runpy
import sys
from pathlib import Path

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.argv = [
    "redbot",
    "discordbot",
    "--cog-path",
    str(Path("local_cogs").resolve()),
    "--load-cogs",
    "audio",
    "djgoowelcome",
]

runpy.run_module("redbot", run_name="__main__")
