from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path


def _package_root() -> Path:
    configured = str(os.environ.get("DJGOO_HOME") or "").strip()
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[1]


def _active_app(root: Path) -> Path:
    path = root / "current.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        relative = str(payload.get("path") or "")
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
        if candidate.is_dir():
            return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return root


def main() -> int:
    root = _package_root()
    app = _active_app(root)
    os.environ["DJGOO_HOME"] = str(root)
    os.environ["DJGOO_APP_ROOT"] = str(app)
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    runpy.run_module("tools.djgoo_portable_stack_entry", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
