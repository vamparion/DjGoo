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
- Automatic Windows Firewall repair for the certificate-pinned local Voice Gateway.
- Multiple independently pinned LAN endpoints in every DjGoo Link invitation.
- A post-release repair and verification workflow that regenerates both updater bundles from the published portable packages.
- Certificate-pinned recipient-led UDP LAN discovery that derives the usable Host address from the reply source instead of trusting adapter enumeration.
- Program-scoped DjGoo Voice outbound firewall rules for UDP discovery and TCP gateway connections on all Windows profiles.
- A public-release audit that rejects detected credentials, private runtime paths, missing public project documents, and incomplete ignore rules.
- Automatic provisioning of an end-to-end encrypted Discord-backed outbound route when the bot has **Manage Webhooks** in the pairing channel.

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
- Made the original Voice Control entrypoint use the generalized keyboard and mouse binding backend, so F5 and mouse-button bindings work even when the supervisor launches the legacy module name.
- Advanced the supervisor capability contract so alpha.16 replaces any alpha.15 process still holding the previous voice-launch code in memory.
- Prevented brief push-to-talk commands from being discarded by extending their effective capture window, padding short clips, and bypassing redundant VAD on the hotkey path.
- Added a higher-accuracy retry only when the fast speech-recognition pass is empty or below the configured confidence thresholds.
- Added a local Nuclear MCP availability probe and circuit breaker so an inactive Nuclear service no longer adds repeated multi-second delays to play commands.
- Prevented ordinary `redbot.command.invoke` diagnostics from erasing Music Core's required readiness fields and triggering a supervisor restart during playback commands.
- Kept the authoritative Redbot heartbeat lease intact while Audio searches and playback commands are still executing.
- Incomplete GitHub releases now report their missing Host updater assets instead of claiming DjGoo is already up to date.
- Recipient pairing probes all direct endpoints concurrently and moves to the encrypted relay before waiting on unreachable LAN addresses.
- Host and recipient windows now size themselves to their DPI-scaled content on first open without adding scrollbars.
- Recipient pairing no longer treats a valid-looking ASTER, VPN, virtual-adapter, stale, or multi-NIC address as authoritative.
- Firewall verification uses structured Windows Firewall metadata when available instead of depending only on localized `netsh` field labels.
- Disabled Windows Firewall profiles no longer cause an unnecessary UAC repair failure.
- Complete `voice_gateway` settings are preserved instead of being discarded by the legacy notification-only secrets loader.
- DjGoo no longer creates a LAN-only invite when no reliable outbound route is available.
- LAN discovery no longer advertises a Host whose certificate-pinned TCP gateway failed to bind.

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
- Push-to-talk recognition uses a beam-one first pass, timestamp-free decoding, and elapsed-time logging while retaining the existing accuracy model and confidence-gated retry.
- DjGoo Link saves every route from an invitation and automatically prefers the route that most recently succeeded.
- Public GitHub releases update without a repository token; private forks retain the encrypted read-only token path.
- Pairing now uses the outbound encrypted route first. LAN discovery and direct TLS are optional backups rather than the primary dependency.

## [0.1.0] - 2026-07-31

### Added

- Deterministic component supervisor with independent Lavalink, Redbot, and voice recovery.
- Continuous F12 voice capture with pre-roll, VAD, confidence rejection, and correction dictionaries.
- Canonical-duration track selection and radio scoring.
- SQLite radio state, queue controls, tests, CI, GPL licensing, and third-party notices.
