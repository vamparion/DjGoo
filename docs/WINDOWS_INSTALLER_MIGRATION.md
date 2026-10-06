# Windows Installer Migration

DjGoo's public Windows product should stop treating a source checkout or an
expanded release archive as an installation. The smallest clean migration is a
per-user Inno Setup installer around the existing versioned application and
runtime layers.

## Installation Contract

- Install immutable program files under `%LOCALAPPDATA%\Programs\DjGoo`.
- Store config, credentials, pairing data, logs, and update state under
  `%LOCALAPPDATA%\DjGoo` so repair, update, and uninstall can preserve user data.
- Bundle Python, Java, Lavalink, WebRTC, launchers, and the updater. Speech stays
  an optional signed and manifest-verified layer installed from Control Center.
- Install Start Menu and optional desktop shortcuts without elevation.
- Register a normal uninstaller and support a repair command that verifies and
  restores program files without touching user data.
- Detect `.git` as Developer Mode. Production update, repair, and migration code
  must refuse to modify that directory.

## Migration Sequence

1. Create an installer project that consumes the existing CI-built Host layers,
   installs them per-user, writes no mutable state into the program directory,
   and produces one `DjGoo-Setup.exe`.
2. Make Control Center the single-instance tray application. Give the background
   Host supervisor a stable ownership record and IPC contract so closing the GUI
   leaves Host running, while `Exit DjGoo` stops every verified owned process.
3. Move updates into a small external bootstrap executable. It verifies a signed
   manifest, stages a complete version beside the active version, atomically
   switches the active pointer, health-checks startup, and rolls back on failure.
4. Add GUI actions for logs, speech install/repair, product repair, Host lifecycle,
   and uninstall. First-run setup writes only to the separate user-data root.
5. Replace portable-release qualification with a clean Windows VM job that runs
   the installer, exercises first run and real playback, closes/reopens the GUI,
   updates while preserving credentials and pairings, repairs, and uninstalls.

## Release Gate

Do not publish the installer until the clean-VM job proves no consoles appear,
Lavalink, Red, web remote, and WebRTC become ready, `!play` reaches real audio,
Host lifecycle commands work, a GUI close does not stop Host, reopening creates
no duplicates, update and rollback preserve user data, repair succeeds, and
uninstall removes program files and owned processes.
