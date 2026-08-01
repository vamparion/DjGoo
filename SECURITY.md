# Security policy

## Supported versions

Security fixes are provided for the latest tagged DjGoo release and the current `main` branch. Pre-release artifacts are for testing and may change without migration guarantees.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving Discord tokens, device credentials, command authorization, remote transports, arbitrary URL playback, dependency supply chain, or secret exposure.

Use GitHub private vulnerability reporting when it is enabled for this repository. Until then, contact the repository owner privately through the GitHub profile associated with this project. Include the affected version, reproduction steps, impact, and whether credentials may have been exposed.

## Secret handling

- Discord bot tokens remain on the Host.
- Voice Remote clients never receive bot tokens or webhook credentials.
- `config/secrets.json`, device credentials, pairing codes, and Red data are excluded from Git.
- Logs must redact authorization headers, tokens, pairing codes, and raw credentials.
- Crash reports are local unless the user explicitly submits them.

A leaked Discord token must be reset in the Discord developer portal. Removing it from Git history does not make the old token safe.

## Remote command threat model

Remote commands must be authenticated to a paired device and Discord user. The Host verifies guild and active voice-channel membership, enforces permissions and rate limits, and uses unique command identifiers so retries cannot duplicate actions.

Pairing codes are single-use, short-lived, and stored only as salted hashes. Device credentials are individually revocable. A relay is not trusted with bot secrets or playback authority.

## Release integrity

Official releases are built by GitHub Actions from a tagged commit. Each release includes SHA-256 checksums, a per-file manifest, the complete GPL license, third-party notices, and a CycloneDX SBOM. Users should obtain packages from the repository's GitHub Releases page and verify the checksum before redistribution.
