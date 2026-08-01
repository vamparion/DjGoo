from __future__ import annotations

from tools.djgoo_portable_stack import configure_core, load_core
from tools.recovery_policy import install_recovery_policy


def main() -> int:
    core = configure_core(load_core())
    install_recovery_policy(core)
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
