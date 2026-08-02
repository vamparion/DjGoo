# Security policy

## Supported versions

Security fixes are provided for the latest tagged DjGoo release and the current `main` branch. Pre-release artifacts are for testing and may change without migration guarantees.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving Discord tokens, device credentials, command authorization, remote transports, arbitrary URL playback, dependency supply chain, or secret exposure.

Use GitHub private vulnerability reporting when it is enabled for this repository. Until then, contact the repository owner privately through the GitHub profile associated with this project. Include the affected version, reproduction steps, impact, and whether credentials may have been exposed.

## Secret handling

- Discord bot tokens remain on the Host.
- DjGoo Voice recipients never receive bot tokens or webhook credentials.
- `config/secrets.json`, update credentials, pairing secrets, device credentials, certificates, relay identities, Red data, and logs are excluded from Git.
- Pairing codes and device tokens are stored by the Host as keyed hashes.
- GitHub update tokens are encrypted for the current Windows account with DPAPI.
- Logs must redact authorization headers, tokens, pairing codes, webhook URLs, and raw credentials.
- Raw microphone audio remains local and is rejected by the command gateway.
- Crash reports remain local unless the user explicitly submits them.

CI runs `tools/public_release_audit.py` before release builds. It rejects detected credentials, private runtime paths, private-key containers, missing public project documents, and incomplete ignore rules. GitHub secret scanning should also be enabled before repository visibility changes.

A leaked Discord, GitHub, relay, or webhook credential must be revoked or rotated. Removing it from Git history does not make the old credential safe.

## Remote command threat model

Every remote command is authenticated to a paired device and Discord user. The Host verifies guild membership, live voice-channel state, command permissions, timestamps, per-device rate limits, and unique command identifiers before accepting the command.

Pairing codes are single-use and short-lived. Device credentials are individually revocable. Commands are attributed to the paired Discord member when Red Audio creates its command context.

The direct Voice Gateway uses a self-signed Host certificate and explicit SHA-256 certificate-fingerprint pinning. Alpha.21 LAN discovery requests include the expected fingerprint and a fresh nonce; only the matching Host responds. The recipient derives the candidate gateway address from the UDP reply source, then performs normal certificate-pinned TLS validation before sending a pairing code or device credential.

Windows Firewall rules are intentionally narrow:

- Host: inbound UDP `47631` for local discovery and inbound TCP `47632` for the pinned gateway, on all profiles.
- Recipient: program-scoped outbound UDP `47631` and outbound TCP `47632`, on all profiles.
- The recipient does not open a general inbound port. Windows Firewall permits replies to its stateful outbound discovery flow.

The direct gateway is intended for a trusted LAN or authenticated private overlay. Do not forward either port directly from a residential router to the public internet.

Internet fallback transports must be outbound-only from the Host, end-to-end encrypted between Host and recipient, and pinned to the Host identity included in the private invite. A Discord or hosted relay must never receive a Discord bot token, become playback authority, or be trusted to authorize commands.

## Public repository checklist

Before changing repository visibility:

1. Run the complete CI suite and `python tools/public_release_audit.py`.
2. Enable GitHub secret scanning, push protection, dependency alerts, and private vulnerability reporting where available.
3. Review the full Git history for credentials; the current-tree audit cannot prove that old commits are clean.
4. Rotate anything that may have appeared in a commit, Actions log, issue, pull request, artifact, or screenshot.
5. Confirm releases contain only the declared seven assets and that updater ZIP membership exactly matches each signed manifest.
6. Keep branch protection on `main` and require the CI/public-release checks before merge.

## Release integrity

Official releases are built by GitHub Actions from a versioned commit. Each release includes Host and recipient packages, verified incremental update manifests, SHA-256 checksums, per-file manifests, the complete GPL license, third-party notices, and CycloneDX SBOMs. Obtain packages from this repository's GitHub Releases page and verify the checksum before redistribution.
