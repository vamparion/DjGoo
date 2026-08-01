# DjGoo

DjGoo is a private, game-first Discord music bot built on Red-DiscordBot Audio.
Its local F12 listener lets people control music without leaving a game.

## What this build changes

- A hidden single-instance supervisor owns Lavalink, Redbot, and the voice listener.
- Start, stop, and reset shortcuts return immediately instead of holding a console open.
- Each component has PID, process-creation-time, and command-line ownership checks.
- A crashed component is restarted independently instead of resetting the entire stack.
- Voice capture uses one continuous microphone stream with pre-roll and release-tail audio.
- The default recognition profile uses `distil-large-v3`, Whisper VAD, beam search, and confidence rejection.
- Artist and title corrections live in JSON instead of hard-coded Python replacements.
- Song selection is ranked against canonical title, artist, ISRC, and duration metadata.
- Obvious albums, playlists, mixes, loops, repeats, tutorials, interviews, and overlong tracks are rejected.
- Radio memory uses SQLite and ordinary skips are negative feedback, not permanent bans.
- Queue seek, removal, shuffle, repeat, autoplay, favorites, and ban undo are exposed to voice/chat commands.

## Install

DjGoo expects Python 3.11, Java 17, and an existing Red-DiscordBot instance in this project directory.

Install or refresh the bot environment using `requirements-bot.txt` and install the voice environment with:

```powershell
.\install-voice-deps.ps1
```

Copy the configuration example:

```powershell
Copy-Item .\config\secrets.example.json .\config\secrets.json
```

Then place the Discord webhook and channel values in `config\secrets.json`.
Secrets and runtime data are ignored by Git.

The first accurate-mode voice start downloads the `distil-large-v3` model. A lower-resource machine can set:

```json
{
  "voice": {
    "model": "small.en",
    "beam_size": 5
  }
}
```

Accuracy is lower with that fallback.

## Shortcuts and startup task

Create portable desktop shortcuts:

```powershell
cscript.exe .\tools\create_djgoo_shortcuts.vbs
```

Install or update automatic startup:

```powershell
cscript.exe .\tools\update_djgoo_startup_task.vbs
```

The scripts derive the installation directory from their own path. They do not contain a user-specific `C:\Users\...` location.

Available actions:

```powershell
.\.venv\Scripts\python.exe .\tools\djgoo_stack.py start
.\.venv\Scripts\python.exe .\tools\djgoo_stack.py stop
.\.venv\Scripts\python.exe .\tools\djgoo_stack.py reset
.\.venv\Scripts\python.exe .\tools\djgoo_stack.py status
.\.venv\Scripts\python.exe .\tools\djgoo_stack.py shutdown
```

`start`, `stop`, and `reset` send a short request to the hidden supervisor and exit. Logs are written under `logs\`.

## Voice control

Hold F12 while speaking and release it after the command.

Examples:

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

Accepted commands play a Windows confirmation sound. Low-confidence or silent captures play an error sound and are not sent to the bot. Set `feedback_beeps` to `false` to disable those sounds.

### Correcting names

Copy `config\voice-corrections.example.json` to `data\voice-corrections.json`, then add phrases Whisper commonly mishears:

```json
{
  "corrections": {
    "lindy stirling": "Lindsey Stirling"
  }
}
```

The default correction file is local runtime data and is not committed.

## Radio

Radio modes are selected as part of the spoken or typed seed:

```text
radio bangers Metallica
radio balanced 2000s rock
radio discovery Lindsey Stirling
radio throwbacks pop
```

- **Bangers** favors the strongest early YouTube Music recommendations and official/Topic uploads.
- **Balanced** mixes strong matches with feedback-guided variety.
- **Discovery** avoids always selecting the safest first recommendation.
- **Throwbacks** prefers recommendations dated 2012 or earlier when year metadata is available.

Station controls:

```text
like this
more like this
less like this
don't play this again
undo last ban
station status
stop radio
```

A normal `skip` lowers a track and artist's radio score and prevents an immediate repeat. Only `don't play this again` creates a persistent station ban.

## Track safety policy

DjGoo rejects tracks longer than ten minutes by default and compares playable candidates with canonical song duration when available. The allowed difference is approximately eight percent, bounded to 18–45 seconds. This blocks most one-hour loops, extended uploads, album videos, and videos substantially longer than the actual recording before they enter the queue.

YouTube watch-radio links are expanded into individually skippable clean tracks. Standard playlist links remain under Red Audio's playlist loader, which normally queues their entries as separate tracks.

## Control panel

Build the web interface after frontend changes:

```powershell
cd control_panel_ui
npm install
npm run build
cd ..
```

Start it with:

```powershell
.\Start-DjGoo-ControlPanel.ps1
```

Then open `http://127.0.0.1:8765`.

## Validation

GitHub Actions compiles the Python source and runs tests for voice parsing, audio preprocessing, process ownership, canonical media selection, radio scoring, and SQLite station migration.

Locally:

```powershell
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.voice-venv\Scripts\python.exe -m pytest
```

## Licensing

DjGoo is licensed under `GPL-3.0-or-later` because it is designed as an extension of the GPL-licensed Red-DiscordBot ecosystem. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.

Muse, JMusicBot, LavaSrc, and SponsorBlock were reviewed as design references. This branch does not copy their source code. Any future code port must receive a separate compatibility and attribution review.

Version-dependent follow-up work is tracked in GitHub issues for the Lavalink/LavaSrc/SponsorBlock migration, in-game transcript choices, and privacy-safe voice ducking.
