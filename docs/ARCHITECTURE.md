# DjGoo architecture

DjGoo is a game-first control layer around Red-DiscordBot Audio. It deliberately keeps one playback authority and treats voice, chat, buttons, and future remote clients as command inputs to that authority.

## Components

### Host launcher

`DjGoo.exe` is the only user-facing process in the portable Host package. It validates the package layout, starts and stops the supervisor, opens setup and diagnostics, and never stores Discord credentials itself.

### Supervisor

The supervisor owns process lifecycle for Lavalink, Redbot, and the local voice listener. Component identity is validated with process ID, process creation time, command-line markers, and fresh health records. A failed component is restarted independently.

The source checkout uses `tools/djgoo_stack.py`. Portable releases retain that file as `djgoo_stack_core.py` and place the explicit runtime adapter at `djgoo_stack.py`.

### Playback authority

Red Audio and Lavalink are the only playback and queue authority. DjGoo adapters call supported Red commands or APIs rather than maintaining a second player.

### Command inputs

All command sources produce the same structured command envelope:

- Discord text commands
- local F12 voice recognition
- Discord buttons
- paired Voice Remote clients

Command sources do not mutate playback state directly.

### Persistent data

Portable packages keep mutable state beside the application:

```text
config/  user-editable configuration and secrets
data/    Red data, radio memory, credentials, models, and health state
logs/    operational logs
```

The remaining application and runtime files are replaceable during an upgrade. Rollback consists of replacing application/runtime files while retaining `config/` and `data/`.

## Distribution

Windows releases are assembled on a clean GitHub Actions runner. The release workflow:

1. runs compilation and the complete test suite;
2. downloads a redistributable CPython 3.11 runtime;
3. installs pinned-compatible Windows dependencies into that runtime;
4. bundles Temurin Java and the Red-compatible Lavalink jar;
5. builds the graphical launcher with PyInstaller;
6. rejects PowerShell and VBS files from the public layout;
7. writes a per-file SHA-256 manifest and CycloneDX SBOM;
8. smoke-tests imports and first-run initialization;
9. publishes a ZIP and checksum.

## Design constraints

- One logical playback leader per Discord guild.
- The Discord bot token never leaves the Host.
- Voice recognition runs locally by default.
- Remote commands are authenticated, attributed, rate-limited, and idempotent.
- The relay, when enabled, is transport only and must not become playback authority.
- Runtime dependencies remain replaceable and visible; DjGoo is not an opaque monolithic binary.
