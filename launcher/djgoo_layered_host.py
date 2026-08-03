from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tools.app_layout import active_app_root, package_root, runtime_python


def main() -> int:
    root = package_root(Path(__file__).resolve().parents[1])
    app = active_app_root(root)
    os.environ["DJGOO_HOME"] = str(root)
    os.environ["DJGOO_APP_ROOT"] = str(app)

    import launcher.djgoo_launcher as base

    @dataclass(frozen=True)
    class LayeredLayout(base.Layout):
        @property
        def app_root(self) -> Path:
            return active_app_root(self.root)

        @property
        def runtime_python(self) -> Path:
            return runtime_python(self.root, "host")

        @property
        def runtime_pythonw(self) -> Path:
            return runtime_python(self.root, "host", windowed=True)

        @property
        def stack_script(self) -> Path:
            return self.app_root / "tools" / "djgoo_portable_stack_entry.py"

        @property
        def setup_script(self) -> Path:
            return self.app_root / "tools" / "portable_red_setup.py"

        @property
        def bot_console_script(self) -> Path:
            return self.app_root / "tools" / "start_redbot_selector.py"

        @property
        def update_worker(self) -> Path:
            return self.app_root / "tools" / "apply_update.py"

    base.application_root = lambda: root
    base.Layout = LayeredLayout

    import launcher.djgoo_host_experience as experience

    experience.application_root = lambda: root
    experience.Layout = LayeredLayout

    import launcher.djgoo_host_control_center as control

    control.application_root = lambda: root
    control.Layout = LayeredLayout
    return int(control.main())


if __name__ == "__main__":
    raise SystemExit(main())
