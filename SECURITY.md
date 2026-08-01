# Security policy

## Supported versions

Security fixes are provided for the latest tagged DjGoo release and the current `main` branch. Pre-release artifacts are for testing and may change without migration guarantees.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving Discord tokens, device credentials, command authorization, remote transports, arbitrary URL playback, dependency supply chain, or secret exposure.

Use GitHub private vulnerability reporting when it is enabled for this repository. Until then, contact the repository owner privately through the GitHub profile associated with this project. Include the affected version, reproduction steps, impact, and whether credentials may have been exposed.

## Secret handling

- Discord bot tokens remain on the Host.
- Voice Remote clients never receive bot tokens or webhook credentials.
- `config/secrets.json`, pairing secrets, device credentials, certificates, and Red data are excluded from Git.
- Pairing codes and device tokens are stored by the Host as keyed hashes.
- Logs must redact authorization headers, tokens, pairing codes, and raw credentials.
- Raw microphone audio remains local and is rejected by the command gateway.
- Crash reports remain local unless the user explicitly submits them.

A leaked Discord token must be reset in the Discord developer portal. Removing it from Git history does not make the old token safe.

## Remote command threat model

Every remote command is authenticated to a paired device and Discord user. The Host verifies guild membership, live voice-channel state, command permissions, timestamps, per-device rate limits, and unique command identifiers before accepting the command.

Pairing codes are single-use and short-lived. Device credentials are individually revocable. Commands are attributed to the paired Discord member when Red Audio creates its command context.

The direct Voice Gateway uses a self-signed Host certificate and explicit SHA-256 certificate-fingerprint pinning. It is intended for a trusted LAN or authenticated private overlay. Do not forward the gateway port directly from a residential router to the public internet. Public relay support requires a separately reviewed outbound-only, end-to-end-encrypted transport.

A relay must never receive a Discord bot token, become playback authority, or be trusted to authorize commands.

## Release integrity

Official releases are built by GitHub Actions from a tagged commit. Each release includes SHA-256 checksums, a per-file manifest, the complete GPL license, third-party notices, and a CycloneDX SBOM. Obtain packages from this repository's GitHub Releases page and verify the checksum before redistribution.
