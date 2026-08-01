## Purpose

<!-- Explain the user problem and the smallest coherent change that solves it. -->

## Changes

<!-- Summarize behavior, architecture, configuration, migrations, and documentation. -->

## Validation

<!-- Include exact automated tests and manual Windows/Discord/relay checks performed. -->

- [ ] Complete platform-independent test suite passes.
- [ ] New or changed state transitions have focused tests.
- [ ] Python sources compile.
- [ ] Windows package workflow passes when launcher, voice, runtime, or release files change.
- [ ] Relay container workflow passes when relay or cryptographic transport files change.

## Architecture and safety

- [ ] Red Audio/Lavalink remains the only playback authority.
- [ ] Voice, chat, buttons, direct clients, and relay clients use one intent/action path.
- [ ] Credentials, tokens, pairing codes, private keys, and authorization headers are not logged or committed.
- [ ] Remote actions remain authenticated, attributed, permission-checked, rate-limited, and replay-safe.
- [ ] Failure is visible and recoverable without rebooting or reinstalling Windows.

## Distribution and compatibility

- [ ] Public packages contain no user-facing `.ps1` or `.vbs` entrypoints.
- [ ] `config/` and `data/` remain compatible or include a documented migration.
- [ ] Dependency/license changes update `THIRD_PARTY_NOTICES.md` and relevant SBOM inputs.
- [ ] README, changelog, architecture, security, or deployment documentation is updated where needed.

## Manual acceptance still required

<!-- List anything CI cannot prove, such as microphone behavior, Discord permissions, live playback, model download, folder relocation, or public TLS deployment. -->
