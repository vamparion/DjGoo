# Testing DjGoo

DjGoo combines platform-independent logic, Windows desktop behavior, Discord integration, audio playback, microphone capture, and an optional public relay. No single test layer proves all of those boundaries.

## Platform-independent suite

Run from a Python 3.11 development environment:

```powershell
python -m pytest -q
```

This suite covers command parsing, audio preprocessing, track policy, radio state, process ownership, health records, portable layouts, pairing, credentials, authorization, replay protection, TLS identity, relay cryptography, opaque routing, and encrypted round trips.

Tests that import the installed Redbot framework are explicitly skipped outside the bot virtual environment. A skip must state that dependency; silent broad exception skips are not acceptable.

## Compilation

```powershell
python -m compileall -q launcher voice tools local_cogs relay tests
```

Compilation catches syntax/import-source problems but does not prove optional dependencies, Windows APIs, Discord permissions, or bundled runtime paths.

## Windows package workflows

The Portable Releases workflow builds Host and Voice Remote on clean Windows runners. Its smoke tests verify:

- public executables are produced;
- bundled runtimes import the expected modules;
- Host first-run setup completes non-interactively;
- package layouts contain no PowerShell or VBS entrypoints;
- ZIPs, checksums, manifests, and SBOMs are produced.

Workflow artifacts are acceptance candidates, not production releases. Record the run ID, artifact ID, size, digest, and expiration in the pull request.

## Relay workflow

The Relay Container workflow verifies:

- signed Host registration;
- stale, replayed, and tampered registration rejection;
- X25519/HKDF/ChaCha20-Poly1305 request and response behavior;
- ciphertext tamper rejection;
- byte-for-byte opaque relay routing;
- full encrypted pairing and accepted-command delivery through a live test server;
- container build and non-root user;
- read-only/no-capability startup;
- live health endpoint.

## Manual evidence

Pull requests must state what CI cannot prove. Relevant evidence may include:

- Windows version and clean extraction path;
- microphone device and model profile;
- Discord bot/account permissions and voice-channel layout;
- exact commands exercised;
- component crash/recovery results;
- multiple-device ordering and requester attribution;
- real-domain relay TLS and different-network testing;
- redacted logs demonstrating failure behavior and secret handling.

Do not upload credentials, private keys, complete configuration files, raw audio, private invite URLs, or personal identifiers as test evidence.

## Regression tests

A defect fix should first reproduce the failure in a focused test whenever the boundary is testable without real external services. The test should fail for the old behavior, pass for the fix, and avoid implementation-specific assertions that prevent safe refactoring.
