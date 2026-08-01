# Security policy

## Supported versions

Security fixes are provided for the latest tagged DjGoo release and the current `main` branch. Pre-release artifacts are for testing and may change without migration guarantees.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving Discord tokens, device credentials, command authorization, cryptographic transports, relay routing, arbitrary URL playback, dependency supply chain, or secret exposure.

Use GitHub private vulnerability reporting when it is enabled for this repository. Until then, contact the repository owner privately through the GitHub profile associated with this project. Include the affected version, reproduction steps, impact, and whether credentials or private keys may have been exposed.

## Secret handling

- Discord bot tokens remain on the Host.
- Voice Remote clients never receive bot tokens or webhook credentials.
- `config/secrets.json`, pairing secrets, device credentials, Host relay private keys, certificates, and Red data are excluded from Git.
- Pairing codes and device tokens are stored by the Host as keyed hashes.
- Logs must redact authorization headers, tokens, pairing codes, decrypted payloads, private keys, and raw credentials.
- Raw microphone audio remains local and is rejected by the direct command gateway.
- Relay requests contain end-to-end encrypted structured commands, never raw microphone audio.
- Crash reports remain local unless the user explicitly submits them.

A leaked Discord token must be reset in the Discord developer portal. Removing it from Git history does not make the old token safe. A leaked device token must be revoked. A leaked Host relay private-key directory requires deleting that identity, generating a new room/key pair, and re-pairing affected devices.

## Remote command threat model

Every remote command is authenticated to a paired device and Discord user. The Host verifies guild membership, live voice-channel state, command permissions, timestamps, per-device rate limits, and unique command identifiers before accepting the command.

Pairing codes are single-use and short-lived. Device credentials are individually revocable. Commands are attributed to the paired Discord member when Red Audio creates its command context.

### Direct gateway

The direct Voice Gateway uses a self-signed Host certificate and explicit SHA-256 certificate-fingerprint pinning. It is intended for a trusted LAN or authenticated private overlay. Do not forward the direct gateway port from a residential router to the public internet.

### Outbound relay

The outbound relay transport uses two layers:

1. public TLS/WSS for connection and routing-metadata protection; and
2. end-to-end X25519/HKDF/ChaCha20-Poly1305 encryption between Voice Remote and Host.

Host relay registration is authenticated with Ed25519 signatures over the room ID, timestamp, and nonce. The room ID is derived from the signing public key. Host encryption public keys are fingerprint-checked by Voice Remote before pairing.

The relay does not receive the Discord bot token and does not authorize or execute commands. It forwards opaque encrypted envelopes. A compromised relay can observe connection metadata and can delay, drop, reorder, or refuse traffic. It should not be able to read pairing codes, device tokens, transcripts, command parameters, or Host responses, or forge an accepted encrypted payload.

Host-side timestamps and command UUID receipts reject stale or duplicated actions even when transport retries occur.

## Relay operation

A public relay operator is responsible for:

- public TLS certificate management;
- infrastructure updates and vulnerability scanning;
- connection-level DDoS and abuse controls;
- monitored availability and incident response;
- privacy-preserving reverse-proxy log retention;
- a public privacy and acceptable-use policy;
- compliance with applicable jurisdictions.

The repository provides a self-hosted relay container and deployment example. It does not itself create or operate an official hosted relay service.

## Release integrity

Official releases are built by GitHub Actions from a tagged commit. Each release includes SHA-256 checksums, a per-file manifest, the complete GPL license, third-party notices, and a CycloneDX SBOM. The relay container workflow emits build provenance and an image SBOM when publishing tagged images to GHCR.

Obtain packages from this repository's GitHub Releases page and verify checksums before redistribution.
