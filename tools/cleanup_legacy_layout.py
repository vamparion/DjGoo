from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from tools.app_layout import active_app_root


LEGACY_APPLICATION_DIRECTORIES = (
    "control_panel",
    "control_panel_dist",
    "launcher",
    "local_cogs",
    "relay",
    "source",
    "voice",
)


def cleanup_legacy_layout(root: Path) -> list[str]:
    root = root.resolve()
    app = active_app_root(root)
    if app == root or not app.is_dir():
        return []
    marker = root / "data" / "layout-migration-alpha25.json"
    if marker.is_file():
        return []
    removed: list[str] = []
    for relative in LEGACY_APPLICATION_DIRECTORIES:
        path = root / relative
        if not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=False)
        removed.append(relative)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "completed_at": time.time(),
                "active_app": str(app.relative_to(root)).replace("\\", "/"),
                "removed": removed,
                "legacy_runtime_preserved": (root / "runtime" / "python").exists(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return removed
