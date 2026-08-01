# Releasing DjGoo

DjGoo uses ordered, reviewable changes and tagged GitHub releases. Do not tag a commit merely because branch CI is green; microphone, Discord, playback, relocation, public TLS, and publisher identity require manual acceptance.

## Merge order for the current architecture

1. Portable Host foundation.
2. Direct paired Voice Remote.
3. Outbound end-to-end encrypted relay.
4. Public-project governance and maintenance files.

After each stacked PR is merged, retarget the next PR to `main`, update it with the new base, and rerun all required checks. Never merge a later stacked PR first merely to avoid resolving its base relationship.

## Versioning

DjGoo follows Semantic Versioning:

- patch: compatible fixes and dependency refreshes;
- minor: new compatible commands, clients, radio behavior, or transports;
- major: incompatible configuration, credential, protocol, command, or data changes.

Pre-release tags such as `v0.4.0-rc.1` are preferred until the project has repeated clean-machine acceptance.

## Automated release gate

The exact commit to tag must pass on `main`:

- complete DjGoo CI;
- Portable Releases Host job;
- Portable Releases Voice Remote job;
- Relay Container test job when relay code exists;
- dependency and licensing review for newly bundled packages;
- clean status with no unresolved required review threads.

Record the passing workflow run IDs in the release notes or release issue.

## Publisher identity and signing

Pull-request and prerelease artifacts may be unsigned while the project is alpha. Stable tags are configured to fail unless these repository settings exist:

- secret `WINDOWS_SIGNING_CERTIFICATE_BASE64`;
- secret `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`;
- variable `WINDOWS_SIGNING_TIMESTAMP_URL`.

The workflow signs both desktop executables with SHA-256 and an RFC 3161 trusted timestamp, verifies them with Windows SignTool, and regenerates the package manifest after the signature changes the executable bytes.

Before a stable release:

- complete issue #12;
- verify the certificate subject is the intended public publisher;
- inspect both executables through the Windows Digital Signatures interface;
- preserve certificate purchase, renewal, revocation, and recovery procedures outside the repository;
- test download and SmartScreen behavior on clean Windows systems.

After the repository becomes public, tagged ZIPs also receive GitHub build-provenance attestations through the release workflow. The step is intentionally skipped while the repository remains private because that GitHub feature is not available to this repository's current plan/visibility combination.

## Host manual acceptance

Using the workflow artifact from the candidate commit:

- verify the published SHA-256 checksum;
- extract to a new writable folder with no source checkout nearby;
- launch `DjGoo.exe` without administrator privileges;
- complete first-run Red/Discord setup using a test bot token;
- start, stop, restart, and inspect component status;
- play, pause, resume, skip, seek, queue, radio, and stop;
- verify local F12 capture and first Whisper model download;
- disconnect network access and confirm the error is actionable;
- terminate Lavalink, Redbot, and voice individually and verify independent recovery;
- move the extracted folder and confirm all relative paths continue working;
- confirm `config/`, `data/`, and `logs/` survive an application-file replacement;
- inspect logs for tokens, webhook URLs, pairing codes, and private keys.

## Direct Voice Remote acceptance

On at least two Windows computers:

- verify the Voice ZIP checksum and extract cleanly;
- pair each device through Discord DM using direct mode;
- select different microphones and test the model download path;
- submit simultaneous songs and controls;
- confirm requester attribution and one authoritative queue;
- confirm same-channel enforcement and destructive-action permissions;
- revoke one device and verify immediate rejection;
- interrupt the network during submission and verify command UUID replay protection;
- confirm no bot token, webhook, or another device credential appears on a client.

## Relay acceptance

On a real public TLS domain and a different internet connection:

- deploy the documented container/proxy stack;
- verify the relay health endpoint and certificate renewal path;
- confirm the Host establishes outbound WSS and reports its room/fingerprint;
- pair through `/djgoorelay pair`;
- submit commands and verify requester attribution;
- stop/restart relay, Host, and Voice Remote independently;
- verify reconnects do not duplicate commands;
- confirm direct LAN mode continues while relay is unavailable;
- inspect relay/proxy logs for plaintext pairing codes, tokens, transcripts, intents, or queries;
- rotate the Host relay identity and confirm old clients fail closed;
- document monitoring, backups, update cadence, abuse response, privacy policy, and incident contacts for any public relay service.

## Tag and publish

After all gates pass:

1. update `CHANGELOG.md` with the version and date;
2. merge the release-preparation change to `main`;
3. create an annotated prerelease tag such as `v0.4.0-rc.1` on the exact accepted commit;
4. push the tag;
5. verify Host and Voice assets are attached to one GitHub Release;
6. verify checksums, manifests, SBOMs, GPL text, and third-party notices;
7. when public, verify GitHub provenance attestations for both ZIPs;
8. verify the relay image tag, provenance, and image SBOM when applicable;
9. download the published assets and repeat a minimal launch/import/signature smoke test;
10. publish release notes with known limitations and upgrade/rollback guidance.

A stable tag such as `v0.4.0` is permitted only after Authenticode configuration and the complete stable-release gate pass.

## Rollback

Keep the previous accepted ZIP and relay image tag available. Desktop rollback replaces application/runtime files but retains a backup of `config/` and `data/`. Restore data only with a documented compatible schema. Relay rollback should use an immutable image tag, not `latest`.
