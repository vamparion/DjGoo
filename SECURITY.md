# Security policy

## Supported versions

Security fixes are provided for the latest tagged DjGoo release and the current `main` branch. Pre-release artifacts are for testing and may change before a stable release.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving Discord tokens, device credentials, command authorization, remote transports, arbitrary URL playback, dependency supply chain, update integrity, or secret exposure.

Use GitHub private vulnerability reporting when it is enabled for this repository. Until then, contact the repository owner privately through the GitHub profile associated with this project. Include the affected version, reproduction steps, impact, and whether credentials may have been exposed.

## Secret handling

- Discord bot tokens remain on the Host and are never included in a pairing invitation.
- A Discord-backed route may place a dedicated webhook capability in the private invitation, but request and response bodies are encrypted to the pinned Host identity before Discord receives them.
- Recipient device credentials and transport capabilities are encrypted for the current Windows account with DPAPI.
- `config/secrets.json`, update credentials, pairing secrets, device credentials, certificates, relay identities, Red data, downloaded models, and logs are excluded from Git.
- Pairing codes and device tokens are stored by the Host as keyed hashes.
- Pairing codes are single-use, expire after five minutes, and may coexist only as sibling routes in the same invitation window.
- GitHub update tokens for private forks are encrypted with DPAPI and are not written to logs.
- Logs must redact authorization headers, tokens, pairing codes, webhook URLs, and raw credentials.
- Raw microphone audio remains local and is rejected by the Host gateway.
- Crash reports remain local unless the user explicitly submits them.

CI runs `tools/public_release_audit.py` before release builds. It rejects detected credentials, private runtime paths, private-key containers, missing public project documents, incomplete ignore rules, and public pull-request workflows that execute untrusted code on self-hosted runners.

A leaked Discord, GitHub, relay, or webhook credential must be revoked or rotated. Removing it from Git history does not make the old credential safe.

## Remote command threat model

Every remote command is authenticated to a paired device and Discord user. The Host verifies guild membership, live voice-channel state, permissions, timestamp, per-device rate limit, and unique command identifier before accepting it.

Pairing requires an outbound encrypted route. When the bot has **Manage Webhooks** in the command channel, DjGoo provisions a dedicated Discord-backed route automatically. Both computers use ordinary outbound HTTPS; Discord carries encrypted envelopes and is not trusted to authorize or interpret commands. A separately hosted WebSocket relay can be configured instead.

The direct Voice Gateway remains an optional LAN optimization. It uses a self-signed Host certificate and explicit SHA-256 certificate-fingerprint pinning. LAN discovery includes the expected fingerprint and a fresh nonce; only the matching Host responds. The recipient derives the candidate address from the authenticated UDP reply and then performs certificate-pinned TLS validation.

Windows Firewall rules are intentionally narrow:

- Host: inbound UDP `47631` for optional discovery and inbound TCP `47632` for the pinned gateway, on all profiles.
- Recipient: program-scoped outbound UDP `47631` and outbound TCP `47632`, on all profiles.
- The recipient does not open a general inbound port. The outbound encrypted route does not require either LAN rule.

Do not forward TCP `47632` or UDP `47631` directly from a residential router to the public internet.

## Application and runtime boundaries

Alpha.25 stores active code in `app/<version>` and selects it through `current.json`. User state remains under package-root `data/`, `config/`, `.localappdata/`, and `logs/`. Large runtime layers remain under `runtime/`.

Incremental Host and Voice updates are required to exclude:

- all `runtime/` files;
- downloaded models;
- Discord, Red, radio, and playback state;
- pairing and transport credentials;
- logs and update backups;
- private configuration.

Update manifests list every archive member with size and SHA-256. The updater rejects absolute paths, traversal, unlisted members, duplicate paths, size mismatches, and hash mismatches before installation. Application files are staged and replaced atomically with rollback.

The optional Host speech runtime has its own manifest and is restricted to `runtime/speech/`. It is downloaded from the same tagged release, verified by bundle and per-file SHA-256, staged separately, and atomically installed. The Host continues to operate without it.

Thin Windows launchers start the package's shared Python runtime and exit. They do not extract code into `%TEMP%`, which removes the PyInstaller `_MEI` cleanup and locked-launcher boundary after the one-time alpha.25 migration.

## Build and release trust boundaries

- Forked public pull requests run only on GitHub-hosted runners when available; they do not execute on AEGIS.
- AEGIS trusted-branch CI runs only for branches pushed inside `vamparion/DjGoo`.
- The fast release lane runs the public audit, compilation, and complete tests before publishing application-only updater assets.
- Full package construction runs only after the fast release succeeds on `main`.
- Runtime caches are content-addressed by Python version, dependency hashes, Java version, Lavalink hash, and Java module set. Cache reuse does not bypass package smoke tests or release verification.
- The minimal Java runtime is generated with `jlink` and must execute the pinned Lavalink jar successfully before packaging.
- The final verifier downloads all release assets and verifies them without rebuilding or replacing published content.

## Public repository checklist

Before changing repository visibility:

1. Run the complete trusted CI suite and `python tools/public_release_audit.py`.
2. Enable GitHub secret scanning, push protection, dependency alerts, and private vulnerability reporting where available.
3. Review the full Git history for credentials; the current-tree audit cannot prove that old commits are clean.
4. Rotate anything that may have appeared in a commit, Actions log, issue, pull request, artifact, release, or screenshot.
5. Confirm the latest release contains exactly the declared nine final assets and that all updater and speech ZIP members match their manifests.
6. Confirm Host and Voice update manifests contain no `runtime/`, private configuration, user data, logs, or credentials.
7. Keep branch protection on `main` and require the public-audit/trusted-CI checks before merge.
8. Confirm the public bot installation grants **Manage Webhooks** only where DjGoo Link will be used, or configure a separately hosted encrypted relay.
9. Verify that no `pull_request` or `pull_request_target` workflow can execute contributor-controlled code on AEGIS with repository or network access.

## Release integrity

A complete release contains nine assets: two clean packages, four application updater assets, two optional speech-runtime assets, and `SHA256SUMS.txt`. Clean packages include versioned application layers, runtime manifests, the complete GPL license, third-party notices, and CycloneDX SBOMs.

Obtain packages only from this repository's GitHub Releases page and verify the checksum before redistribution. The presence of a release tag alone is not completion; all nine assets must be non-empty, downloadable, and pass the final layered-release verification workflow.
