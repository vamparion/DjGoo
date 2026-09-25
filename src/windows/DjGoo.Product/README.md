# DjGoo Windows Product

This solution is the native installed-product boundary. `DjGoo.Host.exe` is a
windowless, single-instance supervisor. It owns child processes through Windows
process handles and a kill-on-close Job Object and accepts versioned, framed
commands over a current-user-only named pipe.

`ProductPaths` separates immutable files under
`%LOCALAPPDATA%\Programs\DjGoo` from mutable state under
`%LOCALAPPDATA%\DjGoo`. Production mutation callers must invoke
`EnsureProductionMutationAllowed` before installer, updater, repair, cleanup, or
migration writes.

`ProductManifest.ParseUnsigned` validates the internal layer manifest contract.
It intentionally does not claim release authenticity. Signature-envelope and
release-key validation belong to the updater stage and must happen before this
parser is used for public release manifests.

The Stage 1 integration executable launches the published self-contained Host,
drives it through a separate IPC client, crashes and restarts an owned child,
checks single-instance behavior and malformed frames, verifies clean shutdown,
and proves an unrelated process is untouched.
