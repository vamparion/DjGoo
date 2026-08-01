# DjGoo

DjGoo is a game-first Discord music controller built around Red-DiscordBot Audio. It provides push-to-talk voice control, clean track selection, radio profiles, paired multi-user voice clients, and resilient process supervision without requiring players to leave a full-screen game.

> Project status: alpha. Portable builds are automated and tested, but Windows/Discord acceptance is still required before broad public promotion.

## Downloads

A tagged release contains two Windows x64 packages:

- `DjGoo-Host-win-x64.zip` — the Discord bot, Red Audio, Lavalink, Host launcher, and optional local voice control.
- `DjGoo-Voice-win-x64.zip` — a smaller local speech-recognition client for everyone else.

Every package includes a per-file SHA-256 manifest and CycloneDX SBOM. The release includes separate SHA-256 checksum files for both ZIPs.

### Host setup

1. Download and verify `DjGoo-Host-win-x64.zip`.
2. Extract it to any writable folder.
3. Run `DjGoo.exe`.
4. Choose **First-run setup** and create your Discord bot application.
5. Use **Test bot console** once to enter the token, prefix, and owner information.
6. Return to `DjGoo.exe` and choose **Start**.

No Python, Java, Node, PowerShell, installer, or administrator access is required by the portable package. Configuration, Red data, downloaded models, device credentials, and logs remain beside the application so the folder can be moved, backed up, or removed cleanly.

```text
DjGoo-Host-win-x64/
├── DjGoo.exe
├── config/
├── data/
├── logs/
├── runtime/
│   ├── java/
│   └── python/
├── local_cogs/
├── tools/
├── voice/
├── manifest.json
└── sbom.cdx.json
```

Public packages contain no `.ps1` or `.vbs` entrypoints. Source-only compatibility and maintenance scripts may remain in the repository.

## Multiple voice users

DjGoo keeps exactly one Discord bot and one playback authority per guild. Additional players run **DjGoo Voice Remote**; they do not invite another bot or receive the Host's Discord token.

### Pair a player on the same LAN

1. Start the DjGoo Host.
2. The player joins the intended Discord voice channel.
3. The player runs `/djgoo pair` or `!djgoo pair` in Discord.
4. DjGoo sends the gateway URL, one-time pairing code, and TLS fingerprint by DM.
5. The player extracts `DjGoo-Voice-win-x64.zip` and runs `DjGoo Voice.exe`.
6. They enter the three DM values, choose a microphone/model/hotkey, and select **Pair device**.
7. They select **Start voice** and hold F12 while speaking.

The Voice Remote performs microphone capture, VAD, Whisper recognition, corrections, and parsing locally. Raw microphone audio is not accepted by the Host gateway. Only a structured command envelope is sent over certificate-pinned HTTPS.

The Host verifies every command against the paired Discord user, guild, current voice channel, device status, rate limits, permissions, timestamp, and command UUID. Destructive controls require server ownership or **Manage Server**.

```text
/djgoo devices
/djgoo revoke <device-id>
```

Pairing codes expire after five minutes and can be redeemed once. Device credentials are individually revocable. See `docs/MULTI_USER_VOICE.md` for the protocol and threat boundaries.

The direct gateway is intended for a trusted LAN or authenticated private overlay. Do not expose it directly to the public internet without a separate deployment review.

## What DjGoo does

- Runs Lavalink, Redbot, and the local Host voice listener under one hidden supervisor.
- Validates process identity and fresh component health instead of trusting stale PID files or log phrases.
- Restarts failed components independently.
- Captures F12 voice commands from a continuous microphone stream with pre-roll and release-tail audio.
- Uses Faster-Whisper, Silero VAD, confidence rejection, and configurable phrase corrections.
- Preserves canonical title, artist, duration, and ISRC metadata during song selection.
- Rejects obvious albums, loops, repeats, mixes, tutorials, interviews, and overlong uploads.
- Scores radio recommendations using station feedback, artist cooldown, result quality, and duration matching.
- Exposes seek, queue removal, shuffle, repeat, autoplay, favorites, and station controls through one intent path.
- Attributes remote playback requests to the paired Discord member rather than an arbitrary active user.

## Voice commands

Hold F12 while speaking and release it after the command.

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

Accepted commands play a confirmation sound. Silent, weak, unauthorized, or low-confidence commands are rejected.

The accurate default profile downloads `distil-large-v3` on first use. Lower-resource computers can select `small.en` at the cost of recognition accuracy.

### Correcting names

Copy `config/voice-corrections.example.json` to `data/voice-corrections.json` and add phrases Whisper commonly mishears:

```json
{
  "corrections": {
    "lindy stirling": "Lindsey Stirling"
  }
}
```

## Radio

```text
radio bangers Metallica
radio balanced 2000s rock
radio discovery Lindsey Stirling
radio throwbacks pop
```

- **Bangers** favors the strongest early recommendations and official/Topic uploads.
- **Balanced** combines strong matches with feedback-guided variety.
- **Discovery** avoids repeatedly selecting the safest first result.
- **Throwbacks** prefers older recommendations when year metadata is available.

```text
like this
more like this
less like this
don't play this again
undo last ban
station status
stop radio
```

A normal skip produces temporary negative feedback. Only an explicit ban creates a persistent station block.

## Develop from source

Source development currently targets Windows 10/11 x64 and Python 3.11.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-bot.txt -r requirements-dev.txt

py -3.11 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -U pip
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt -r requirements-dev.txt
```

Run tests:

```powershell
.\.voice-venv\Scripts\python.exe -m pytest -q
```

Run source launchers:

```powershell
.\.venv\Scripts\python.exe -m launcher.djgoo_launcher
.\.voice-venv\Scripts\python.exe -m launcher.djgoo_voice_launcher
```

Legacy root scripts are compatibility entrypoints for existing source checkouts. New user-facing functionality belongs in the launchers or importable Python modules.

## Release engineering

The Windows release workflow builds Host and Voice Remote in parallel, then publishes both atomically:

- compiles source and runs security, parser, audio, persistence, and existing behavior tests;
- assembles redistributable Python and Java runtimes where needed;
- installs binary Windows dependencies into isolated portable runtimes;
- bundles the Red-compatible Lavalink jar only with Host;
- builds `DjGoo.exe` and `DjGoo Voice.exe` with PyInstaller;
- smoke-tests both clean package layouts;
- rejects `.ps1` and `.vbs` files from public packages;
- creates per-file manifests, CycloneDX SBOMs, ZIP checksums, and GitHub artifacts;
- publishes both assets through one tagged GitHub Release.

See `docs/ARCHITECTURE.md`, `docs/MULTI_USER_VOICE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`.

## Licensing

DjGoo is licensed under `GPL-3.0-or-later`. The complete license is in `LICENSE`; dependency and design-reference notices are in `THIRD_PARTY_NOTICES.md`.

Muse, JMusicBot, LavaSrc, and SponsorBlock were reviewed as design references. Their source code is not included unless a future change explicitly documents the port, compatibility review, and required attribution.
