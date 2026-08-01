# Contributing to DjGoo

DjGoo accepts focused pull requests that preserve one playback authority and keep the user experience usable from a full-screen game.

## Development environment

Use Python 3.11 on Windows for runtime-sensitive work. Create separate bot and voice environments using the repository requirement files. Linux CI covers platform-independent logic, while portable packaging and microphone behavior require Windows validation.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-bot.txt -r requirements-dev.txt

py -3.11 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -U pip
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt -r requirements-dev.txt
```

Run the complete test suite before opening a pull request:

```powershell
.\.voice-venv\Scripts\python.exe -m pytest -q
```

## Pull-request expectations

- Keep lifecycle, voice, transport, and playback changes separable when possible.
- Add tests for parsing, state transitions, authorization, migrations, and failure recovery.
- Document manual Windows or Discord checks that CI cannot perform.
- Do not introduce a second playback queue or player.
- Do not log secrets, device credentials, raw authorization headers, or microphone audio.
- Update `THIRD_PARTY_NOTICES.md` and the SBOM inputs when dependencies change.
- Use supported Red Audio interfaces before duplicating existing Red behavior.

## Repository structure

- `launcher/` — user-facing desktop launcher
- `tools/` — supervisor, setup, release, and maintenance code
- `voice/` — capture, recognition, parsing, transports, and remote client logic
- `local_cogs/` — Red integration and playback adapters
- `tests/` — platform-independent and guarded integration tests
- `docs/` — architecture and operational documentation

## Compatibility

DjGoo currently targets Windows 10/11 x64, CPython 3.11, Red-DiscordBot 3.5, and the Red-compatible Lavalink release line. Changes to these boundaries require a migration plan and a clean-package smoke test.
