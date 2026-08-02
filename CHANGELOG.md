# Changelog

DjGoo follows Semantic Versioning. Dates use ISO 8601.

## [Unreleased]

### Added

- Portable Windows Host package with one `DjGoo.exe` launcher.
- Separate portable `DjGoo Voice.exe` package for paired users.
- Bundled CPython runtimes and a Host-only Temurin Java runtime.
- Guided first-run Red and Discord setup.
- Discord pairing, device listing, and device revocation commands.
- One-time pairing codes and individually revocable device credentials.
- Certificate-pinned HTTPS Voice Gateway with Discord voice-channel authorization.
- Per-device rate limits, stale-command rejection, and duplicate-command protection.
- Requester-aware Red Audio contexts for paired remote users.
- GitHub Actions release artifacts, SHA-256 checksums, per-file manifests, and CycloneDX SBOMs.
- Public architecture, multi-user voice, contribution, and security documentation.
- Automated alpha prerelease publishing from versioned `release/v...` branches.
- CI enforcement preventing PowerShell and VBScript files from being committed to the repository.
- Verified incremental Host update ZIPs and external file manifests.
- A **Check for updates** launcher action with automatic backup, rollback, restart, and stack-resume behavior.
- Windows-DPAPI encryption for private-repository update credentials.
- Verified incremental updates inside `DjGoo Voice`, with recipient-specific release manifests and rollback.
- **Bind a button** capture for keyboard, mouse, function, navigation, and media buttons on both Host and recipient.
- One shared visual palette for Host and recipient control centers.

### Fixed

- Added `pip` to the embedded Host runtime because Red imports it during startup.
- Bound Red's configuration module directly to the package-local `config.json` instead of relying on Windows environment path overrides.
- Made Windows package jobs fail when native Python smoke tests return nonzero exit codes.
- Kept Red console startup errors visible for diagnosis.
- Preserved and recognized existing Discord/Music Core state when upgrading or moving a portable DjGoo folder.
- Stopped treating the idle background supervisor as an active Music Core process when changing Discord configuration.
- Kept newly bundled Audio Engine files when migrating older user configuration.
- Replaced the obsolete `redbot.exe` diagnostics probe with the portable supervisor PID and heartbeat state.
- Health failures now identify the exact Audio Engine, Music Core, or Voice Control component and expose its current error logs.

### Changed

- Tagged releases build Host and Voice Remote in parallel and publish both together.
- Launch, setup, supervision, and maintenance entrypoints are implemented as tested Python modules.
- Removed the obsolete PowerShell and VBScript compatibility layer from the source repository.
- Runtime-specific paths are handled by an explicit portable supervisor adapter.
- Voice Remote clients perform speech recognition locally and send structured commands rather than microphone audio.
- Normal Host updates preserve Java, models, user data, logs, settings, and secrets instead of replacing the complete package.
- Windows package smoke tests now verify portable Red configuration, bundled `pip`, DPAPI credential storage, and incremental-update scope.
- Host and recipient updater assets are published together from one validated Windows build.
- Recipient incremental updates preserve the active embedded Python runtime, pairing credential, local settings, and logs.

## [0.1.0] - 2026-07-31

### Added

- Deterministic component supervisor with independent Lavalink, Redbot, and voice recovery.
- Continuous F12 voice capture with pre-roll, VAD, confidence rejection, and correction dictionaries.
- Canonical-duration track selection and radio scoring.
- SQLite radio state, queue controls, tests, CI, GPL licensing, and third-party notices.
