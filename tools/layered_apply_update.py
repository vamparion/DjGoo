from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable

from tools import apply_update as legacy
from tools.app_layout import active_app_root, runtime_python
from tools.portable_environment import portable_environment


def invoke_layered_stack(
    root: Path,
    action: str,
    log: Callable[[str], None],
) -> None:
    """Stop or start the Host stack in layered and migrated installations."""

    root = root.resolve()
    python = runtime_python(root, "host")
    root_bootstrap = root / "tools" / "djgoo_stack.py"
    active_entry = active_app_root(root) / "tools" / "djgoo_portable_stack_entry.py"
    stack = root_bootstrap if root_bootstrap.is_file() else active_entry
    if not python.is_file() or not stack.is_file():
        log(
            f"Stack {action} skipped because the layered runtime or supervisor "
            f"entrypoint is missing (python={python}, stack={stack})."
        )
        return
    try:
        completed = subprocess.run(
            [str(python), str(stack), action],
            cwd=root,
            env=portable_environment(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        log(f"Requested layered stack {action} (exit {completed.returncode}).")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"Layered stack {action} request could not complete: {exc}")


def main(argv: Iterable[str] | None = None) -> int:
    legacy.invoke_stack = invoke_layered_stack
    return int(legacy.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
