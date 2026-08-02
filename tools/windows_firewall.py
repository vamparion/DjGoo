from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import time
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


def _netsh_field(output: str, name: str) -> str:
    expected = name.strip().lower()
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == expected:
            return value.strip().lower()
    return ""


def _field_tokens(value: str) -> set[str]:
    return {
        item.strip().lower()
        for item in value.replace(";", ",").replace(" ", ",").split(",")
        if item.strip()
    }


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
    profiles = _field_tokens(_netsh_field(output, "profiles"))
    # The previous alpha.19 rule covered only Domain/Private profiles. Windows
    # commonly classifies cellular, hotspot, and ASTER networks as Public, which
    # made the rule look valid while recipients still timed out.
    all_profiles = "all" in profiles or {
        "domain",
        "private",
        "public",
    }.issubset(profiles)
    local_ports = _field_tokens(_netsh_field(output, "localport"))
    return bool(
        result.returncode == 0
        and _netsh_field(output, "enabled") == "yes"
        and _netsh_field(output, "direction") == "in"
        and _netsh_field(output, "action") == "allow"
        and _netsh_field(output, "protocol") == "tcp"
        and str(int(port)) in local_ports
        and all_profiles
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
        "profile=any",
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
    command = subprocess.list2cmdline(["netsh", *_netsh_arguments(port)])
    path = Path(tempfile.gettempdir()) / f"djgoo-firewall-{os.getpid()}.cmd"
    path.write_text(
        "@echo off\r\n"
        + command
        + "\r\nexit /b %errorlevel%\r\n",
        encoding="utf-8",
    )
    try:
        launched = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(path),
                None,
                str(path.parent),
                0,
            )
        )
        if launched <= 32:
            return False
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if firewall_rule_ready(port):
                return True
            time.sleep(0.5)
        return False
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def ensure_gateway_firewall(
    project_root: Path,
    *,
    port: int = 47632,
) -> tuple[bool, str]:
    """Ensure the Host accepts recipient connections on every network profile."""

    if os.name != "nt":
        return True, "not-windows"
    marker = project_root / "data" / "gateway-firewall.json"
    if firewall_rule_ready(port):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "rule": RULE_NAME,
                    "port": int(port),
                    "profiles": "any",
                    "ready": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return True, "already-ready"

    success = _add_rule_direct(port) if _is_admin() else _add_rule_elevated(port)
    if not success:
        return False, (
            "Windows did not allow the DjGoo Voice Gateway firewall rule on all "
            "network profiles. Local recipients cannot connect until the UAC "
            "request is approved."
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "rule": RULE_NAME,
                "port": int(port),
                "profiles": "any",
                "ready": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return True, "created"
