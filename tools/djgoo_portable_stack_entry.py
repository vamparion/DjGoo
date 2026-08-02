from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.djgoo_portable_stack import configure_core, load_core
from tools.input_binding_adapter import install_input_binding
from tools.recovery_policy import install_recovery_policy


def main() -> int:
    core = configure_core(load_core())
    install_recovery_policy(core)
    install_input_binding(core)
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
