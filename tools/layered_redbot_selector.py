from __future__ import annotations

import os
from pathlib import Path

from tools.app_layout import active_app_root, package_root
from tools.portable_environment import apply_portable_environment


def main() -> int:
    root = package_root(Path(__file__).resolve().parents[1])
    app = active_app_root(root)
    os.environ["DJGOO_HOME"] = str(root)
    os.environ["DJGOO_APP_ROOT"] = str(app)
    apply_portable_environment(root)

    from tools import start_redbot_selector as selector

    selector.PROJECT_ROOT = root
    return int(selector.main())


if __name__ == "__main__":
    raise SystemExit(main())
