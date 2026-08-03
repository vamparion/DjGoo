# Changelog

DjGoo follows Semantic Versioning. Dates use ISO 8601.

## [Unreleased]

### Added

- Portable Windows Host and DjGoo Voice packages with verified in-application updates.
- Guided Red, Discord, firewall, and multi-user pairing setup.
- End-to-end encrypted Discord-backed recipient transport with certificate-pinned LAN and direct fallbacks.
- One-time pairing codes, persistent Windows-protected device credentials, per-device revocation, replay rejection, rate limiting, and requester-aware Red Audio contexts.
- General keyboard, mouse, navigation, media, and function-key capture through **Bind a button** on Host and recipient.
- Public architecture, contribution, security, and multi-user protocol documentation.
- Public-release audit for credentials, private runtime paths, required project files, ignore rules, and unsafe self-hosted pull-request workflows.
- Host and recipient Windows Firewall repair with narrow, program-appropriate rules on every network profile.
- Versioned application directories under `app/<version>` with an atomic `current.json` active-version pointer.
- Hash-keyed AEGIS caches for Host Python, recipient Python, shared speech dependencies, Lavalink, and minimal Java runtime layers.
- A `jlink` Java 17 runtime containing only the modules required to execute the pinned Lavalink build.
- Extraction-free, sub-512-KiB Windows launchers for Host, Mini Player, and DjGoo Voice.
- A separately downloadable and verified `DjGoo-SpeechRuntime` asset for optional Host speech recognition.
- A fast application-release lane that publishes Host and Voice updater assets before full runtime packages finish building.
- A final verifier that downloads all nine release assets and validates hashes, archive membership, manifests, app pointers, and runtime boundaries without modifying the release.

### Fixed

- Embedded Host runtimes include `pip`, which Red imports during startup.
- Red configuration and user data are bound to the extracted DjGoo folder rather than user-global Windows paths.
- Startup and health failures identify the exact Lavalink, Redbot, or Voice component and preserve useful logs.
- Existing Discord, Red, radio, update, pairing, and model state survives updates and folder moves.
- Push-to-talk captures retain short speech, use a fast first decode, and retry for accuracy only when needed.
- Optional inactive integrations no longer add repeated multi-second delays to playback requests.
- Incomplete GitHub releases report the exact missing updater assets instead of claiming DjGoo is current.
- Host and recipient windows remain within the Windows work area and above the taskbar.
- LAN pairing no longer trusts guessed ASTER, VPN, virtual-adapter, stale, or multi-NIC addresses.
- Disabled Windows Firewall profiles no longer cause meaningless repair failures.
- Gateway discovery starts only after the certificate-pinned TCP listener is actually bound.
- DjGoo refuses to issue a LAN-only invitation when no reliable outbound encrypted route is available.
- Complete `voice_gateway` relay configuration is retained instead of being discarded by legacy secret loading.
- Recipient pairing remains visibly in progress until its DPAPI credential is written and reopened.
- Current Host supervisors are not restarted merely because update and startup timestamps were written in a different order.
- Every connection route in one invitation receives a valid coexisting pairing code; creating later route codes no longer invalidates the Discord route before the invitation is sent.
- Thin launchers eliminate PyInstaller `_MEI...` extraction directories and the associated close-time cleanup warning.
- Alpha.25 application updates exclude Python, Java, speech libraries, Lavalink, models, logs, credentials, and user state.
- The legacy post-release repair job can no longer regenerate updater bundles from full packages and restore the obsolete flat layout.

### Changed

- Pairing tries the encrypted outbound route first; LAN discovery and direct TLS are optional backups.
- Raw microphone audio remains local. Recipients send authenticated structured commands only.
- Public releases update without a GitHub token; private forks retain encrypted read-only token support.
- Host local speech recognition is optional. Music playback, Discord commands, remote recipients, and all non-speech Host functions remain available without downloading the speech layer.
- DjGoo Voice clean packages include the speech layer because recognition is their primary local function.
- Clean Host packages use `runtime/python-bot`; clean recipient packages use `runtime/python-voice`; both may share the independently packaged `runtime/speech` layer.
- The Host package contains a minimal Java runtime rather than a complete development kit.
- Alpha.25 performs one deferred launcher migration from older PyInstaller executables. Alpha.26 and later can replace the small launchers directly because they exit immediately after starting the shared Python application.
- Full first-install archives are compressed as standard ZIPs with multithreaded 7-Zip when available and a compatible Python ZIP fallback.
- Runtime/full-package construction no longer blocks updater visibility for existing installations.

## [0.1.0] - 2026-07-31

### Added

- Deterministic component supervisor with independent Lavalink, Redbot, and voice recovery.
- Continuous push-to-talk capture with pre-roll, VAD, confidence rejection, and correction dictionaries.
- Canonical-duration track selection and radio scoring.
- SQLite radio state, queue controls, tests, CI, GPL licensing, and third-party notices.
