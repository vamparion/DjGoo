# Third-party notices

DjGoo is licensed under **GPL-3.0-or-later**. It integrates with or distributes separately maintained open-source projects. Those projects remain governed by their own licenses and copyright notices.

## Bundled release components

| Project | Purpose in DjGoo | License |
|---|---|---|
| CPython | Portable Python runtime | Python Software Foundation License |
| Eclipse Temurin / OpenJDK | Portable Java runtime | GPL-2.0 with Classpath Exception |
| Cog-Creators/Red-DiscordBot and Red-Lavalink | Discord framework, Audio cog, and Lavalink client | GPL-3.0 |
| Cog-Creators/Lavalink-Jars / Lavalink | Red-compatible audio playback server | Apache-2.0 repository tooling; Lavalink MIT |
| faster-whisper | Local Whisper inference | MIT |
| CTranslate2 | Inference runtime used by faster-whisper | MIT |
| Silero VAD, distributed through faster-whisper | Voice activity detection | MIT |
| ytmusicapi | YouTube Music metadata and recommendations | MIT |
| python-sounddevice and PortAudio | Microphone capture | MIT |
| NumPy | Numerical audio processing | BSD-3-Clause |
| SciPy | Resampling and audio filtering | BSD-3-Clause |
| psutil | Process identity, supervision, and termination | BSD-3-Clause |
| aiohttp | Discord webhook and command transport HTTP | Apache-2.0 |

The portable release includes the license and notice files shipped by the bundled Python and Java distributions. `sbom.cdx.json` records the exact Python packages in each build, while `manifest.json` records every released file and its SHA-256 digest.

## Build dependencies

| Project | Purpose | License |
|---|---|---|
| PyInstaller | Builds the graphical `DjGoo.exe` launcher | GPL-2.0-or-later with the PyInstaller bootloader exception |
| GitHub Actions | Reproducible tests and release assembly | Service; individual actions retain their licenses |

PyInstaller's exception permits distributing applications produced by its bootloader without imposing PyInstaller's GPL terms on the generated application beyond DjGoo's existing GPL license.

## Design references

The following projects were reviewed for feature and architecture ideas, but no source code from them is included unless a future change explicitly says otherwise:

- museofficial/muse — MIT
- jagrosh/MusicBot — Apache-2.0
- Just-Some-Bots/MusicBot — MIT
- topi314/LavaSrc — MIT
- topi314/SponsorBlock-Plugin — MIT

Future source-code ports from any design reference must be reviewed separately, retain required copyright and license notices, and remain compatible with DjGoo's GPL-3.0-or-later license.

## Service and content terms

Open-source licensing does not grant permission to bypass the terms of YouTube, Discord, Spotify, SponsorBlock, or another network service. Deployers are responsible for their API credentials, account permissions, service terms, and the media they request or store.
