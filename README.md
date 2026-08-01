# DjGoo

DjGoo is a game-first Discord music controller built around Red-DiscordBot Audio. It provides local push-to-talk voice control, clean track selection, radio profiles, and resilient process supervision without requiring players to leave a full-screen game.

> Project status: alpha. The source implementation works, but public binary releases still require Windows and Discord acceptance testing before the repository should be announced broadly.

## Download and run

Portable Windows builds are produced by the **Portable Host** GitHub Actions workflow.

1. Download `DjGoo-Host-win-x64.zip` from a tagged GitHub Release or a pull-request workflow artifact.
2. Verify the ZIP against `SHA256SUMS.txt`.
3. Extract it to any writable folder.
4. Run `DjGoo.exe`.
5. Choose **First-run setup**, create your Discord bot application, and then use **Test bot console** once to enter the bot token and prefix.
6. Return to the launcher and choose **Start**.

No Python, Java, Node, PowerShell, installer, or administrator access is required for the portable package. Configuration, Red data, downloaded voice models, and logs remain beside the application so the folder can be moved, backed up, or removed cleanly.

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

The public package intentionally contains no `.ps1` or `.vbs` entrypoints. Source-only maintenance scripts may remain in the repository for development compatibility.

## What DjGoo does

- Runs Lavalink, Redbot, and the local voice listener under one hidden supervisor.
- Validates process identity and fresh component health instead of trusting stale PID files or log phrases.
- Restarts failed components independently.
- Captures F12 voice commands from one continuous microphone stream with pre-roll and release-tail audio.
- Uses Faster-Whisper, Silero VAD, confidence rejection, and configurable phrase corrections.
- Preserves canonical title, artist, duration, and ISRC metadata during song selection.
- Rejects obvious albums, loops, repeats, mixes, tutorials, interviews, and overlong uploads.
- Scores radio recommendations using station feedback, artist cooldown, result quality, and duration matching.
- Exposes seek, queue removal, shuffle, repeat, autoplay, favorites, and station controls through the same intent path.

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

Accepted commands play a confirmation sound. Silent, weak, or low-confidence captures are rejected locally.

The accurate default profile downloads `distil-large-v3` on first use. Lower-resource computers can set `small.en` in `config/secrets.json` at the cost of recognition accuracy.

### Correcting names

Copy `config/voice-corrections.example.json` to `data/voice-corrections.json` and add phrases that Whisper commonly mishears:

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

## Multiple voice users

DjGoo keeps one Discord bot and one playback authority per guild. Additional players will use the separate **DjGoo Voice Remote** package, which recognizes speech on each player's computer and submits authenticated commands to the Host. Remote clients never receive the Discord bot token or run another music bot.

The multi-user transport and pairing implementation is developed separately so it can be security-reviewed without destabilizing Host packaging.

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

Run the source launcher:

```powershell
.\.venv\Scripts\python.exe -m launcher.djgoo_launcher
```

Legacy root scripts are compatibility entrypoints for existing source checkouts. New user-facing functionality belongs in the launcher or importable Python modules.

## Release engineering

The Windows release workflow:

- compiles the Python source and runs the complete test suite;
- assembles redistributable Python and Java runtimes;
- installs Windows dependencies into the portable runtime;
- bundles the Red-compatible Lavalink jar;
- builds `DjGoo.exe` with PyInstaller;
- smoke-tests clean-package imports and setup;
- rejects `.ps1` and `.vbs` files from the public package;
- creates a per-file SHA-256 manifest, CycloneDX SBOM, ZIP checksum, and GitHub artifact;
- publishes tagged builds through GitHub Releases.

See `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`.

## Licensing

DjGoo is licensed under `GPL-3.0-or-later`. The complete license is in `LICENSE`; dependency and design-reference notices are in `THIRD_PARTY_NOTICES.md`.

Muse, JMusicBot, LavaSrc, and SponsorBlock were reviewed as design references. Their source code is not included unless a future change explicitly documents the port, license compatibility, and required attribution.
