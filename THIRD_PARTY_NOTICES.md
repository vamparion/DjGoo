# Third-party notices

DjGoo is licensed under **GPL-3.0-or-later**. It integrates with or depends on
separately maintained open-source projects. Those projects remain governed by
their own licenses and copyright notices.

## Runtime and build dependencies

| Project | Purpose in DjGoo | License |
|---|---|---|
| Cog-Creators/Red-DiscordBot and Red-Lavalink | Discord bot framework, Audio cog, Lavalink client | GPL-3.0 |
| Lavalink | Audio playback server | MIT |
| faster-whisper | Local Whisper inference | MIT |
| Silero VAD, distributed through faster-whisper | Voice activity detection | MIT |
| ytmusicapi | YouTube Music metadata and recommendations | MIT |
| python-sounddevice | PortAudio microphone capture | MIT |
| NumPy | Numerical audio processing | BSD-3-Clause |
| SciPy | Resampling and audio filtering | BSD-3-Clause |
| psutil | Process identity, supervision, and termination | BSD-3-Clause |
| aiohttp | Discord webhook HTTP client | Apache-2.0 |

Dependency packages are installed separately by the setup scripts. DjGoo does
not relicense those packages. Binary distributions must preserve all notices
required by the versions actually distributed.

## Design references

The following projects were reviewed for feature and architecture ideas, but no
source code from them is included in this change:

- museofficial/muse — MIT
- jagrosh/MusicBot — Apache-2.0
- Just-Some-Bots/MusicBot — MIT
- topi314/LavaSrc — MIT
- topi314/SponsorBlock-Plugin — MIT

Future source-code ports from any design reference must be reviewed separately,
retain required copyright and license notices, and remain compatible with
DjGoo's GPL-3.0-or-later license.

## Service and content terms

Open-source licensing does not grant permission to bypass the terms of YouTube,
Discord, Spotify, SponsorBlock, or any other network service. Deployers are
responsible for their own API credentials, account permissions, service terms,
and the media they request or store.
