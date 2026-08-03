# DjGoo architecture

DjGoo is a game-first control layer around Red-DiscordBot Audio. It keeps one playback authority and treats voice, chat, buttons, and remote clients as authenticated command inputs to that authority.

## Package layers

Alpha.25 separates application code, runtime dependencies, and mutable state:

```text
DjGoo/
├── DjGoo.exe                    thin Host launcher
├── DjGoo Mini Player.exe        thin overlay launcher
├── current.json                 active application pointer
├── app/
│   └── <version>/               immutable DjGoo application layer
├── runtime/
│   ├── python-bot/              Host/Red dependencies
│   ├── python-voice/            recipient transport/UI dependencies
│   ├── speech/                  Faster-Whisper and audio dependencies
│   └── java/                    minimal Lavalink jlink image
├── config/                      user configuration and secrets
├── data/                        Red, radio, pairing, models, health, updates
├── .localappdata/               package-local Red configuration
└── logs/                        operational logs
```

`current.json` is an atomic pointer to one `app/<version>` directory. Application updates install a complete new version and then switch the pointer. Runtime files and user state are not members of normal updater archives.

The first alpha.25 update preserves older combined runtimes and replaces the old PyInstaller executables through the existing detached completion mechanism. The new launchers start the shared Python runtime and exit immediately. Later updates can replace those launchers directly because no bootloader remains resident and no `_MEI` directory is created.

## Components

### Host control center

`DjGoo.exe` selects the active application layer and starts `launcher.djgoo_layered_host` with `runtime/python-bot`. The control center validates package state, manages the supervisor, opens setup and diagnostics, checks for updates, and can install or repair the optional Host speech runtime.

The launcher contains no Python interpreter, application archive, Discord credential, or user state.

### Recipient control center

`DjGoo Voice.exe` starts `launcher.djgoo_layered_voice` with `runtime/python-voice` and adds `runtime/speech/Lib/site-packages` to the module path. Pairing credentials and recipient settings remain at package root so changing the active application layer does not disconnect the device.

### Supervisor

The supervisor owns lifecycle for Lavalink, Redbot, and optional Host voice recognition. Component identity is validated with process ID, creation time, command-line markers, and fresh health records. A failed component is restarted independently.

The active app contains the supervisor implementation. A small root bootstrap exists only to resume the stack safely during migration and update handoff. The supervisor resolves executables from package-root runtime layers and source modules from the active app layer.

If the Host speech layer is absent, the supervisor omits only the local voice component. Lavalink, Redbot, Discord commands, radio, paired recipients, and playback remain available.

### Playback authority

Red Audio and Lavalink are the only playback and queue authority. DjGoo adapters call supported Red commands or APIs rather than maintaining a second player.

### Command inputs

All command sources produce the same structured command envelope:

- Discord text and slash commands;
- local Host push-to-talk, when the optional speech layer is installed;
- Discord buttons;
- paired DjGoo Voice recipients.

Command inputs do not mutate playback state directly.

### Remote transport

Pairing invitations require at least one end-to-end encrypted outbound route. Discord-backed or hosted relay traffic is transport only and cannot authorize commands or become playback authority. Certificate-pinned LAN discovery and direct TLS routes are optional backups.

A pairing invitation may contain multiple route-specific one-time codes. Those sibling codes coexist for the same five-minute invitation, but each individual code can be redeemed only once. Successful redemption returns a persistent, individually revocable device credential.

## Update architecture

### Fast application release

The fast lane runs the public audit, compilation, and complete tests. It builds:

- one Host app layer;
- one Voice app layer;
- three small Windows launchers;
- Host and Voice update ZIP/JSON pairs.

These updater archives contain `app/<version>`, `current.json`, small bootstrap/update tools, and launchers where needed. They exclude all `runtime/` content and mutable state. The four updater assets are published and downloaded back before the runtime build begins.

### Runtime and clean-package release

The full lane runs after the fast lane succeeds. AEGIS stores content-addressed runtime layers keyed by:

- embedded Python version and checksum;
- Host, Voice-base, and speech requirement-file hashes;
- Java version;
- Lavalink jar SHA-256;
- `jdeps`/`jlink` module set.

The Host Python layer contains Red and bot dependencies. The Voice Python layer contains networking, encryption, UI support, and updater requirements. Speech dependencies are installed once into a separate layer and reused by Voice packages and the optional Host speech asset.

The Java layer is generated with `jlink`, strips development files and debug metadata, and must successfully run the pinned Lavalink jar before use. DjGoo does not package a complete JDK.

Clean Host and Voice directories are assembled from the already-validated app and runtime layers. Standard ZIP archives are produced with multithreaded 7-Zip when available, with a compatible Python ZIP fallback.

### Final verification

The final verifier downloads the nine declared assets and checks:

- release tag and prerelease metadata;
- non-empty/downloadable assets;
- unified checksums;
- updater bundle hashes and exact member lists;
- absence of runtime files from incremental updates;
- speech asset path confinement to `runtime/speech/`;
- clean-package app pointers, launchers, and runtime directories;
- ZIP integrity and manifest agreement.

It does not rebuild, repair, or overwrite published content.

## Persistent data and rollback

Mutable state remains outside `app/`:

```text
config/          secrets and user-editable settings
data/            Red data, radio memory, credentials, models, health, updates
.localappdata/   package-local Red instance configuration
logs/            operational logs
```

An application rollback restores the previous app directory and `current.json`. Runtime installation uses separate staging and rollback. User state is not copied into either transaction.

## Design constraints

- One logical playback leader per Discord guild.
- The Discord bot token never leaves the Host.
- Raw microphone audio remains local.
- Remote commands are authenticated, attributed, rate-limited, and idempotent.
- Relays are transport only and must not become playback authority.
- Public contributor code never executes on the self-hosted AEGIS runner.
- Runtime dependencies remain visible, independently verifiable, and replaceable rather than hidden inside opaque one-file executables.
