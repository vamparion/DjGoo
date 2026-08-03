# DjGoo

DjGoo is a game-first Discord music controller built on Red-DiscordBot Audio and Lavalink. It provides local push-to-talk control, paired multi-user voice clients, safer track selection, radio profiles, and resilient process supervision without requiring players to leave a full-screen game.

> **Status:** alpha. Automated source, update, package, and public-release validation is active. Real Windows, microphone, Discord, and mixed-network acceptance testing is still required before a stable release.

## Download

Use the repository's **Releases** section rather than downloading the source ZIP.

A complete Windows x64 release contains nine verified assets:

- `DjGoo-Host-win-x64.zip` — complete first-install Host package with the Discord bot, Red Audio, Lavalink, a portable Python runtime, a minimal Java runtime, and extraction-free Windows launchers.
- `DjGoo-Voice-win-x64.zip` — complete recipient package with the Voice application, portable Python runtime, and local speech-recognition layer.
- `DjGoo-Host-update.zip` and `DjGoo-Host-update.json` — runtime-independent Host application update and manifest.
- `DjGoo-Voice-update.zip` and `DjGoo-Voice-update.json` — runtime-independent recipient application update and manifest.
- `DjGoo-SpeechRuntime-win-x64.zip` and `DjGoo-SpeechRuntime.json` — optional Host speech-recognition layer and manifest.
- `SHA256SUMS.txt` — checksums for every package and updater asset.

The packages require no separately installed Python, Java, Node, PowerShell, or installer. Each clean package includes file manifests and CycloneDX runtime SBOMs.

## Package layout

Alpha.25 separates frequently changing DjGoo code from large, rarely changing runtimes:

```text
DjGoo/
├── DjGoo.exe
├── DjGoo Mini Player.exe
├── current.json
├── app/
│   └── 0.3.0-alpha.25/
├── runtime/
│   ├── python-bot/
│   ├── java/
│   └── speech/             optional on Host
├── data/
├── config/
└── logs/
```

The Windows executables are small launchers that start the shared portable runtime. They do not use PyInstaller one-file extraction and do not create `_MEI...` temporary directories. `current.json` selects the active versioned application layer, allowing application updates and rollback without replacing Python, Java, speech libraries, models, or user data.

## Host quick start

1. Download `DjGoo-Host-win-x64.zip` and `SHA256SUMS.txt` from Releases.
2. Verify the package checksum, then extract it into any writable folder.
3. Run `DjGoo.exe`.
4. Approve the first Windows UAC request. DjGoo creates narrowly scoped inbound rules for TCP `47632` and UDP `47631` on all Windows network profiles.
5. Select **Connect Discord** and configure a Discord bot application.
6. Select **Start**.

Local Host speech recognition is optional. Select **Install local voice** in the Host control center to download and verify the separate speech runtime. Discord commands, music playback, paired recipients, and every non-speech Host function work without that layer.

Configuration, Red data, downloaded models, paired-device credentials, and logs remain outside `app/`. Moving or updating the application layer does not replace them.

## Updating

Use **Check for updates** in `DjGoo.exe` or `DjGoo Voice.exe`. The fast release workflow publishes the Host and Voice application updates first. Existing installations can therefore update without waiting for clean Python, Java, speech, and first-install packages to be rebuilt.

DjGoo verifies the selected release, manifest, bundle size, SHA-256 digest, archive membership, path safety, and every file hash. It then performs backup, atomic replacement, rollback on failure, and restart. Alpha.25 performs one deferred replacement to migrate older PyInstaller launchers. Later thin-launcher updates no longer require that compatibility step.

Normal updates preserve:

- portable Python, minimal Java, and speech runtime layers;
- downloaded speech models;
- Discord and Red configuration;
- pairing credentials and Host device records;
- radio history, settings, logs, and user data.

Public releases require no GitHub token. Private forks may request a fine-grained token with read-only **Contents** access; DjGoo encrypts it for the current Windows account with DPAPI and does not write it to logs.

## Multiple voice users

A Discord server uses one DjGoo Host and one playback authority. Other players run DjGoo Voice; they do not create another Discord bot and never receive the Host's bot token.

```text
Player 1 microphone ─┐
Player 2 microphone ─┼── authenticated commands ── DjGoo Host ── Red Audio ── Lavalink
Player 3 microphone ─┘
```

### Pair a recipient

1. Start the Host and join the intended Discord voice channel.
2. Run `/djgoolink pair` in Discord. DjGoo sends a private five-minute invitation.
3. Open `DjGoo Voice.exe` on the recipient computer.
4. Paste the complete invitation and select **Paste and connect**.
5. After pairing succeeds, DjGoo Voice stores a Windows-protected device credential and reconnects in later sessions without another five-minute invitation.

The five-minute limit applies only to initial pairing. The paired device credential has no five-minute session limit and remains valid until revoked or removed.

Connection order is:

1. end-to-end encrypted Discord-backed or hosted outbound route;
2. certificate-pinned recipient-led LAN discovery;
3. certificate-pinned direct route hints.

The outbound route uses ordinary HTTPS and does not require router port forwarding or an inbound recipient firewall rule. The optional LAN path avoids guessed ASTER, VPN, virtual-adapter, stale, and multi-NIC addresses by deriving the Host address from an authenticated discovery response.

Speech recognition and parsing run locally. Raw microphone audio is rejected by the Host gateway. Only structured command metadata is transmitted. The Host validates the paired device, Discord user, guild, current voice channel, permissions, timestamp, rate limit, and command UUID for every request.

```text
/djgoolink status
/djgoo devices
/djgoo revoke <device-id>
```

Do not forward TCP `47632` or UDP `47631` from a residential router to the public internet. See `docs/MULTI_USER_VOICE.md` and `SECURITY.md` for protocol and threat boundaries.

## Core behavior

- Supervises Lavalink, Redbot, and optional local Host voice recognition independently.
- Verifies process identity and fresh health state instead of trusting stale PID files or log phrases.
- Captures push-to-talk audio with pre-roll and release-tail buffering.
- Uses Faster-Whisper, VAD, confidence rejection, and configurable phrase corrections.
- Preserves canonical title, artist, duration, and ISRC metadata during resolution.
- Rejects obvious albums, loops, repeats, mixes, tutorials, interviews, and overlong uploads.
- Scores radio recommendations with station feedback, artist cooldown, duration matching, and result quality.
- Supports seek, queue removal, shuffle, repeat, autoplay, favorites, and station controls through one intent path.
- Attributes remote playback requests to the paired Discord member.

## Voice examples

```text
play Sandstorm
skip
pause
resume
seek 1:30
remove number three from the queue
shuffle the queue
toggle repeat
toggle autoplay
add to favorites
queue
what is playing
```

The accurate default model is `distil-large-v3`. Lower-resource computers can select `small.en` with reduced recognition accuracy.

To correct commonly misheard names, copy `config/voice-corrections.example.json` to `data/voice-corrections.json` and edit its mappings.

## Radio examples

```text
radio bangers Metallica
radio balanced 2000s rock
radio discovery Lindsey Stirling
radio throwbacks pop
```

```text
like this
more like this
less like this
don't play this again
undo last ban
station status
stop radio
```

A normal skip creates temporary negative feedback. Only an explicit ban creates a persistent block.

## Public repository safety

Never commit `config/secrets.json`, `data/`, `logs/`, `.localappdata/`, private keys, pairing credentials, update tokens, Discord bot tokens, or webhook URLs.

CI runs `tools/public_release_audit.py` and rejects detected credentials, private runtime paths, missing license/security documents, unsafe public pull-request workflows, or an incomplete `.gitignore`. Forked pull-request code does not execute on the self-hosted AEGIS release machine.

This audit supplements GitHub secret scanning; it does not make a leaked credential safe. Rotate anything that may have appeared in Git history, Actions logs, issues, pull requests, artifacts, or screenshots before changing repository visibility.

## Develop from source

Source development targets Windows 10/11 x64 and Python 3.11.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-bot.txt -r requirements-dev.txt

py -3.11 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -U pip
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt -r requirements-dev.txt

.\.voice-venv\Scripts\python.exe tools/public_release_audit.py
.\.voice-venv\Scripts\python.exe -m pytest -q
```

Run source applications directly:

```powershell
.\.venv\Scripts\python.exe -m launcher.djgoo_host_experience
.\.voice-venv\Scripts\python.exe -m launcher.djgoo_voice_experience
```

## Release engineering

Alpha.25 uses three release stages:

1. **Fast Application Release** runs the public audit, compilation, and complete test suite; builds versioned Host/Voice app layers and tiny launchers; publishes and downloads the four updater assets.
2. **Portable Releases** reuses hash-keyed Python and speech layers from AEGIS, builds a `jlink` Java runtime for Lavalink, assembles clean packages, creates standard multithreaded ZIP archives, and appends full-package and optional-speech assets to the same prerelease.
3. **Verify layered release assets** downloads all nine final assets and verifies checksums, updater manifests, archive membership, runtime exclusion, versioned app pointers, and clean-package contracts without rebuilding or modifying the release.

Runtime caches are keyed by the Python version, dependency-file hashes, Java version, Lavalink hash, and required Java modules. A normal application change does not reinstall or rehash those runtime layers in the update path.

See `docs/ARCHITECTURE.md`, `docs/MULTI_USER_VOICE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`.

## License

DjGoo is licensed under `GPL-3.0-or-later`. The complete license is in `LICENSE`; bundled dependency and design-reference notices are in `THIRD_PARTY_NOTICES.md`.
