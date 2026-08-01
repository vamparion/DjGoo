# DjGoo

DjGoo is a game-first Discord music controller built on Red-DiscordBot Audio and Lavalink. It provides local push-to-talk control, paired multi-user voice clients, safer track selection, radio profiles, and resilient process supervision without requiring players to leave a full-screen game.

> **Status:** alpha. Automated source and package validation is active. Real Windows, microphone, and Discord acceptance testing is still required before a stable public release.

## Download

Use the repository's **Releases** section rather than downloading the source ZIP.

Each release provides two Windows x64 packages:

- `DjGoo-Host-win-x64.zip` — the Discord bot, Red Audio, Lavalink, portable Python and Java runtimes, `DjGoo.exe`, and optional local voice recognition.
- `DjGoo-Voice-win-x64.zip` — `DjGoo Voice.exe` and the local speech-recognition runtime for additional users.

The packages require no separate Python, Java, Node, PowerShell, installer, or administrator setup. Each package includes a file manifest and CycloneDX SBOM; each ZIP has a matching SHA-256 checksum file.

### Host quick start

1. Download `DjGoo-Host-win-x64.zip` from Releases.
2. Verify it with `SHA256SUMS-Host.txt`.
3. Extract the ZIP into any writable folder.
4. Run `DjGoo.exe`.
5. Select **First-run setup** and create a Discord bot application.
6. Use **Test bot console** once to enter the token, prefix, and owner information.
7. Close the console and select **Start**.

Configuration, Red data, downloaded models, paired-device credentials, and logs remain inside the extracted folder. The folder can be moved, backed up, or deleted without an installer.

## Multiple voice users

A Discord server uses one DjGoo Host and one playback authority. Other players run DjGoo Voice Remote; they do not create another Discord bot and never receive the Host's Discord token.

```text
Player 1 microphone ─┐
Player 2 microphone ─┼── paired commands ── DjGoo Host ── Red Audio ── Lavalink
Player 3 microphone ─┘
```

### Pair a Voice Remote on a trusted LAN

1. Start the Host and join the intended Discord voice channel.
2. The additional player runs `/djgoo pair` or `!djgoo pair` in Discord.
3. DjGoo sends the gateway URL, one-time pairing code, and TLS fingerprint by DM.
4. The player extracts `DjGoo-Voice-win-x64.zip` and runs `DjGoo Voice.exe`.
5. They enter the pairing details, select a microphone, model, and hotkey, then select **Pair device**.
6. They select **Start voice** and hold F12 while speaking.

Speech recognition and parsing run locally. Raw microphone audio is rejected by the Host gateway. Only structured command metadata is transmitted over certificate-pinned HTTPS.

The Host validates the paired device, Discord user, guild, current voice channel, permissions, timestamp, rate limit, and command UUID for every request. Destructive controls require server ownership or **Manage Server**.

```text
/djgoo devices
/djgoo revoke <device-id>
```

The direct gateway is intended for a trusted LAN or authenticated private overlay. Do not forward it directly to the public internet. See `docs/MULTI_USER_VOICE.md` for the protocol and threat boundaries.

## Core behavior

- Supervises Lavalink, Redbot, and local voice recognition as independent components.
- Verifies process identity and fresh health state instead of trusting stale PID files or log phrases.
- Captures push-to-talk audio continuously with pre-roll and release-tail buffering.
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

## Develop from source

Source development currently targets Windows 10/11 x64 and Python 3.11.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-bot.txt -r requirements-dev.txt

py -3.11 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -U pip
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt -r requirements-dev.txt

.\.voice-venv\Scripts\python.exe -m pytest -q
```

Run the Python applications directly:

```powershell
.\.venv\Scripts\python.exe -m launcher.djgoo_launcher
.\.voice-venv\Scripts\python.exe -m launcher.djgoo_voice_launcher
```

The repository intentionally contains no `.ps1` or `.vbs` application entrypoints. Launch, setup, supervision, and maintenance behavior belongs in tested Python modules. CI enforces this boundary.

## Release engineering

GitHub Actions builds Host and Voice Remote on clean Windows runners. The release pipeline:

- compiles source and runs the complete automated test suite;
- assembles redistributable Python and Java runtimes where required;
- installs binary Windows dependencies into isolated portable runtimes;
- bundles the Red-compatible Lavalink jar only with Host;
- creates `DjGoo.exe` and `DjGoo Voice.exe` with PyInstaller;
- smoke-tests both extracted package layouts;
- rejects PowerShell and VBScript files;
- creates manifests, CycloneDX SBOMs, ZIP checksums, and workflow artifacts;
- publishes tagged releases and alpha prereleases with both packages attached.

See `docs/ARCHITECTURE.md`, `docs/MULTI_USER_VOICE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`.

## License

DjGoo is licensed under `GPL-3.0-or-later`. The complete license is in `LICENSE`; bundled dependency and design-reference notices are in `THIRD_PARTY_NOTICES.md`.
