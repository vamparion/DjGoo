# DjGoo

DjGoo is a game-first Discord music controller built on Red-DiscordBot Audio and Lavalink. It provides local push-to-talk control, paired multi-user voice clients, safer track selection, radio profiles, and resilient process supervision without requiring players to leave a full-screen game.

> **Status:** alpha. Automated source and package validation is active. Real Windows, microphone, Discord, and mixed-network acceptance testing is still required before a stable release.

## Download

Use the repository's **Releases** section rather than downloading the source ZIP.

A complete Windows x64 release contains seven updater-visible assets:

- `DjGoo-Host-win-x64.zip` — complete first-install Host package, including the Discord bot, Red Audio, Lavalink, portable Python and Java runtimes, `DjGoo.exe`, and optional local voice recognition.
- `DjGoo-Voice-win-x64.zip` — complete recipient package containing `DjGoo Voice.exe` and its local speech-recognition runtime.
- `DjGoo-Host-update.zip` and `DjGoo-Host-update.json` — verified incremental Host update and manifest.
- `DjGoo-Voice-update.zip` and `DjGoo-Voice-update.json` — verified incremental recipient update and manifest.
- `SHA256SUMS.txt` — checksums for all published packages and updater assets.

The packages require no separate Python, Java, Node, PowerShell, or installer. Each complete package includes a file manifest and CycloneDX SBOM.

## Host quick start

1. Download `DjGoo-Host-win-x64.zip` from Releases and verify its entry in `SHA256SUMS.txt`.
2. Extract the ZIP into any writable folder.
3. Run `DjGoo.exe`.
4. Approve the first Windows UAC request. DjGoo creates narrowly scoped inbound rules for TCP gateway port `47632` and UDP discovery port `47631` on all Windows network profiles.
5. Select **Connect Discord** and configure a Discord bot application.
6. Select **Start**.

Configuration, Red data, downloaded models, paired-device credentials, and logs remain inside the extracted folder. The folder can be moved, backed up, or deleted without an installer.

## Updating

Use **Check for updates** in either `DjGoo.exe` or `DjGoo Voice.exe`. DjGoo downloads the product-specific incremental ZIP and manifest, verifies the release version, bundle size, SHA-256 digest, archive paths, and every file hash, then performs a backup, atomic replacement, rollback on failure, and launcher restart.

Normal updates preserve runtimes that are intentionally outside the incremental scope, models, bot data, logs, settings, Discord credentials, pairing credentials, and user secrets.

Public GitHub releases are checked without a GitHub token. A private fork or private pre-release repository may request a fine-grained token with read-only **Contents** access; DjGoo encrypts it for the current Windows account with DPAPI and does not write it to logs. This token is unrelated to the Discord bot token.

## Multiple voice users

A Discord server uses one DjGoo Host and one playback authority. Other players run DjGoo Voice; they do not create another Discord bot and never receive the Host's Discord token or webhook credentials.

```text
Player 1 microphone ─┐
Player 2 microphone ─┼── authenticated commands ── DjGoo Host ── Red Audio ── Lavalink
Player 3 microphone ─┘
```

### Pair a recipient

1. Start the Host and join the intended Discord voice channel.
2. Run `/djgoolink pair` in Discord. DjGoo sends a private, five-minute invite containing a one-time code, the Host TLS identity, and every available fallback transport.
3. Extract `DjGoo-Voice-win-x64.zip` and run `DjGoo Voice.exe`.
4. Approve the first UAC request. DjGoo Voice creates only two program-scoped outbound rules: UDP `47631` for LAN discovery and TCP `47632` for the pinned gateway. It does not expose an inbound recipient port.
5. Paste the complete invite and select **Paste and connect**.

Alpha.21 and later do not trust a guessed Host adapter address. The recipient broadcasts a short discovery request containing the expected TLS fingerprint. Only the matching Host responds, and the recipient derives the usable gateway URL from the reply's source address. This avoids stale, VPN, ASTER, virtual-adapter, and multi-NIC addresses.

Connection order is:

1. certificate-pinned recipient-led LAN discovery;
2. any still-valid direct invite hints;
3. end-to-end encrypted Discord or hosted relay fallback when configured.

Speech recognition and parsing run locally. Raw microphone audio is rejected by the Host gateway. Only structured command metadata is transmitted. The Host validates the paired device, Discord user, guild, current voice channel, permissions, timestamp, rate limit, and command UUID for every request.

```text
/djgoolink status
/djgoo devices
/djgoo revoke <device-id>
```

The direct gateway is for a trusted LAN or authenticated private overlay. Do not forward TCP `47632` or UDP `47631` from a residential router to the public internet. See `docs/MULTI_USER_VOICE.md` and `SECURITY.md` for protocol and threat boundaries.

## Core behavior

- Supervises Lavalink, Redbot, and local voice recognition as independent components.
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

DjGoo keeps runtime state beside the extracted package, but those paths are excluded from Git. Never commit `config/secrets.json`, `data/`, `logs/`, `.localappdata/`, private keys, pairing credentials, update tokens, Discord bot tokens, or webhook URLs.

CI runs `tools/public_release_audit.py` and rejects detected credentials, private runtime paths, missing license/security documents, or an incomplete `.gitignore`. This audit supplements GitHub secret scanning; it does not make a leaked credential safe. Rotate any credential that was ever committed before changing repository visibility.

Security reports should use GitHub private vulnerability reporting after it is enabled. Do not place credentials or exploitable details in public issues.

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

Run the Python applications directly:

```powershell
.\.venv\Scripts\python.exe -m launcher.djgoo_host_experience
.\.voice-venv\Scripts\python.exe -m launcher.djgoo_voice_experience
```

The repository intentionally contains no committed `.ps1` or `.vbs` application entrypoints. Launch, setup, supervision, and maintenance behavior belongs in tested Python modules. CI enforces this boundary.

## Release engineering

The self-hosted Windows release pipeline:

- runs the public-release audit, source compilation, and complete automated test suite;
- assembles redistributable Python and Java runtimes where required;
- installs binary dependencies into isolated portable runtimes;
- creates the Host and recipient PyInstaller executables;
- smoke-tests the generated packages under their bundled runtimes;
- creates manifests, CycloneDX SBOMs, updater ZIPs, and SHA-256 checksums;
- rejects updater bundles containing logs, secrets, credentials, user data, or files outside the declared manifest;
- publishes only after all seven release assets are non-empty and downloadable.

See `docs/ARCHITECTURE.md`, `docs/MULTI_USER_VOICE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`.

## License

DjGoo is licensed under `GPL-3.0-or-later`. The complete license is in `LICENSE`; bundled dependency and design-reference notices are in `THIRD_PARTY_NOTICES.md`.
