# Changelog

DjGoo follows Semantic Versioning. Dates use ISO 8601.

## [Unreleased]

### Added

- Portable Windows Host package with one `DjGoo.exe` launcher.
- Bundled CPython and Temurin Java runtimes.
- Guided first-run Red and Discord setup.
- GitHub Actions release artifacts, SHA-256 checksums, per-file manifest, and CycloneDX SBOM.
- Public architecture, contribution, and security documentation.

### Changed

- Public release packages no longer expose PowerShell or VBS entrypoints.
- Runtime-specific paths are handled by an explicit portable supervisor adapter.

## [0.1.0] - 2026-07-31

### Added

- Deterministic component supervisor with independent Lavalink, Redbot, and voice recovery.
- Continuous F12 voice capture with pre-roll, VAD, confidence rejection, and correction dictionaries.
- Canonical-duration track selection and radio scoring.
- SQLite radio state, queue controls, tests, CI, GPL licensing, and third-party notices.
