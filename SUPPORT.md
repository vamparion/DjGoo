# DjGoo support

DjGoo is currently alpha software. Support is provided through reproducible GitHub issues rather than private access to a user's computer or Discord credentials.

## Before opening a bug

1. Confirm the exact release tag, commit SHA, or workflow artifact run.
2. Read the package `manifest.json` and verify the ZIP checksum.
3. Reproduce the issue after using the launcher **Restart** action.
4. Check component state and the newest files under `logs/`.
5. Search existing issues and pull requests.
6. Test whether the problem affects typed commands, local F12 voice, Voice Remote, or all command sources.

## Useful diagnostics

Include only the relevant information:

- Windows version and architecture;
- Host or Voice Remote package version;
- microphone device name and selected Whisper model;
- Discord guild/channel permission context without private invite links;
- launcher component status;
- redacted startup, component, voice, or relay log lines;
- exact spoken or typed command and the observed result;
- whether the machines are on the same LAN, a private overlay, or the encrypted relay;
- relay container image tag and `/healthz` response when applicable.

## Never post

- Discord bot tokens;
- webhook URLs;
- device tokens or credential JSON files;
- pairing codes;
- Host TLS or relay private keys;
- complete `config/secrets.json` files;
- private server invites;
- raw microphone recordings without the speaker's informed consent;
- unredacted logs containing personal identifiers.

Security-sensitive problems follow `SECURITY.md`, not the public issue tracker.

## Supported environments

The portable desktop products target Windows 10/11 x64. The self-hosted relay targets a maintained Linux container host behind public TLS. Source builds on other platforms are welcome, but they are not release-blocking until documented and covered by CI.

## Scope

Maintainers can help diagnose DjGoo behavior, package integrity, documented configuration, and reproducible compatibility defects. They cannot recover Discord accounts, operate a public relay on behalf of users, grant media rights, or guarantee third-party network services remain available.
