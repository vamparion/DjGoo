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

### Changed

- Tagged releases build Host and Voice Remote in parallel and publish both together.
- Public release packages no longer expose PowerShell or VBS entrypoints.
- Runtime-specific paths are handled by an explicit portable supervisor adapter.
- Voice Remote clients perform speech recognition locally and send structured commands rather than microphone audio.

## [0.1.0] - 2026-07-31

### Added

- Deterministic component supervisor with independent Lavalink, Redbot, and voice recovery.
- Continuous F12 voice capture with pre-roll, VAD, confidence rejection, and correction dictionaries.
- Canonical-duration track selection and radio scoring.
- SQLite radio state, queue controls, tests, CI, GPL licensing, and third-party notices.
