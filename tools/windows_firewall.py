from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
from pathlib import Path


RULE_NAME = "DjGoo Voice Gateway"


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def firewall_rule_ready(port: int = 47632) -> bool:
    if os.name != "nt":
        return True
    result = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={RULE_NAME}",
            "verbose",
        ],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    normalized = output.lower()
    return bool(
        result.returncode == 0
        and "enabled:" in normalized
        and "yes" in normalized
        and "protocol:" in normalized
        and "tcp" in normalized
        and str(int(port)) in normalized
    )


def _netsh_arguments(port: int) -> list[str]:
    return [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={RULE_NAME}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={int(port)}",
        "profile=private,domain",
        "enable=yes",
    ]


def _add_rule_direct(port: int) -> bool:
    subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={RULE_NAME}",
        ],
        capture_output=True,
        creationflags=_creation_flags(),
    )
    result = subprocess.run(
        ["netsh", *_netsh_arguments(port)],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    return result.returncode == 0 and firewall_rule_ready(port)


def _add_rule_elevated(port: int) -> bool:
    arguments = " ".join(
        '"' + item.replace('"', '\\"') + '"'
        for item in _netsh_arguments(port)
    )
    script = (
        "$p = Start-Process -FilePath netsh.exe "
        f"-ArgumentList '{arguments.replace("'", "''")}' "
        "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    return result.returncode == 0 and firewall_rule_ready(port)


def ensure_gateway_firewall(
    project_root: Path,
    *,
    port: int = 47632,
) -> tuple[bool, str]:
    """Ensure the Host accepts same-network recipient connections.

    Windows requires elevation to change inbound firewall policy.  The first Host
    launch can therefore show one normal UAC prompt.  Success is recorded so the
    check remains quiet on later launches, while the actual firewall rule is
    still verified before trusting the marker.
    """

    if os.name != "nt":
        return True, "not-windows"
    marker = project_root / "data" / "gateway-firewall.json"
    if firewall_rule_ready(port):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"rule": RULE_NAME, "port": int(port), "ready": True}) + "\n",
            encoding="utf-8",
        )
        return True, "already-ready"

    success = _add_rule_direct(port) if _is_admin() else _add_rule_elevated(port)
    if not success:
        return False, (
            "Windows did not allow the DjGoo Voice Gateway firewall rule. "
            "Local recipients cannot connect until the UAC request is approved."
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"rule": RULE_NAME, "port": int(port), "ready": True}) + "\n",
        encoding="utf-8",
    )
    return True, "created"
