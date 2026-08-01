# Maintainers

## Current maintainer

- `@vamparion` — project owner and final release authority

## Ownership boundaries

Changes in these areas require explicit maintainer review even when automated checks pass:

- Discord bot token handling and Red instance setup;
- playback authority, Red Audio callbacks, and Lavalink compatibility;
- pairing, device credentials, authorization, and user-data deletion;
- TLS, cryptography, direct transport, and relay protocol changes;
- release workflows, bundled runtimes, checksums, manifests, SBOMs, and container publication;
- license, third-party notices, privacy, and security policy;
- destructive command permissions and requester attribution.

## Release authority

Only the project owner should create production tags while the project has one maintainer. A release tag is created only after the stacked implementation PRs are merged in order, all required checks pass on `main`, and the manual acceptance checklist in `docs/RELEASING.md` is complete.

## Adding maintainers

A future maintainer should demonstrate sustained, reviewable contributions; understand the single-playback-authority design; follow responsible disclosure; and be able to test Windows packaging or relay operations. Repository administration, package publication, and relay infrastructure access should be granted separately and with the least privilege required.

## Bus-factor work

The project should continue moving operational knowledge from private memory into versioned documentation, tests, scripts, and release checklists. Secrets, signing credentials, DNS access, and relay infrastructure recovery procedures must not be committed to the repository.
