from __future__ import annotations

import os
from pathlib import Path

from tools.app_layout import active_app_root, package_root
from tools.cleanup_legacy_layout import cleanup_legacy_layout


def main() -> int:
    root = package_root(Path(__file__).resolve().parents[1])
    app = active_app_root(root)
    os.environ["DJGOO_HOME"] = str(root)
    os.environ["DJGOO_APP_ROOT"] = str(app)
    cleanup_legacy_layout(root)

    import launcher.djgoo_voice_launcher as voice_base

    voice_base.application_root = lambda: root
    import launcher.djgoo_voice_control_center as control

    control.voice_base.application_root = lambda: root
    return int(control.main())


if __name__ == "__main__":
    raise SystemExit(main())
