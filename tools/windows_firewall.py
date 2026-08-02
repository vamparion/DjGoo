from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from voice.lan_discovery import DISCOVERY_PORT


RULE_NAME = "DjGoo Voice Gateway"
DISCOVERY_RULE_NAME = "DjGoo Voice Discovery"


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


def _rule_ready(
    rule_name: str,
    *,
    protocol: str,
    port: int,
) -> bool:
    if os.name != "nt":
        return True
    result = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={rule_name}",
            "verbose",
        ],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    profiles = _field_tokens(_netsh_field(output, "profiles"))
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
        and _netsh_field(output, "protocol") == protocol.strip().lower()
        and str(int(port)) in local_ports
        and all_profiles
    )


def firewall_rule_ready(port: int = 47632) -> bool:
    return _rule_ready(
        RULE_NAME,
        protocol="tcp",
        port=int(port),
    )


def discovery_firewall_rule_ready(
    port: int = DISCOVERY_PORT,
) -> bool:
    return _rule_ready(
        DISCOVERY_RULE_NAME,
        protocol="udp",
        port=int(port),
    )


def _rule_arguments(
    rule_name: str,
    *,
    protocol: str,
    port: int,
) -> list[str]:
    return [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={rule_name}",
        "dir=in",
        "action=allow",
        f"protocol={protocol.upper()}",
        f"localport={int(port)}",
        "profile=any",
        "enable=yes",
    ]


def _netsh_arguments(port: int) -> list[str]:
    return _rule_arguments(
        RULE_NAME,
        protocol="TCP",
        port=int(port),
    )


def _discovery_netsh_arguments(port: int) -> list[str]:
    return _rule_arguments(
        DISCOVERY_RULE_NAME,
        protocol="UDP",
        port=int(port),
    )


def _delete_rule(rule_name: str) -> None:
    subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={rule_name}",
        ],
        capture_output=True,
        creationflags=_creation_flags(),
    )


def _add_rule(arguments: list[str]) -> bool:
    result = subprocess.run(
        ["netsh", *arguments],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    return result.returncode == 0


def _add_rules_direct(
    gateway_port: int,
    discovery_port: int,
) -> bool:
    _delete_rule(RULE_NAME)
    _delete_rule(DISCOVERY_RULE_NAME)
    if not _add_rule(_netsh_arguments(gateway_port)):
        return False
    if not _add_rule(_discovery_netsh_arguments(discovery_port)):
        return False
    return bool(
        firewall_rule_ready(gateway_port)
        and discovery_firewall_rule_ready(discovery_port)
    )


def _add_rules_elevated(
    gateway_port: int,
    discovery_port: int,
) -> bool:
    commands = [
        subprocess.list2cmdline(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "delete",
                "rule",
                f"name={RULE_NAME}",
            ]
        ),
        subprocess.list2cmdline(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "delete",
                "rule",
                f"name={DISCOVERY_RULE_NAME}",
            ]
        ),
        subprocess.list2cmdline(["netsh", *_netsh_arguments(gateway_port)]),
        "if errorlevel 1 exit /b %errorlevel%",
        subprocess.list2cmdline(
            ["netsh", *_discovery_netsh_arguments(discovery_port)]
        ),
        "if errorlevel 1 exit /b %errorlevel%",
    ]
    path = Path(tempfile.gettempdir()) / f"djgoo-firewall-{os.getpid()}.cmd"
    path.write_text(
        "@echo off\r\n"
        + "\r\n".join(commands)
        + "\r\nexit /b 0\r\n",
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
            if (
                firewall_rule_ready(gateway_port)
                and discovery_firewall_rule_ready(discovery_port)
            ):
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
    discovery_port: int = DISCOVERY_PORT,
) -> tuple[bool, str]:
    """Allow pinned gateway TCP and recipient-led discovery UDP on all profiles."""

    if os.name != "nt":
        return True, "not-windows"
    marker = project_root / "data" / "gateway-firewall.json"
    ready = bool(
        firewall_rule_ready(port)
        and discovery_firewall_rule_ready(discovery_port)
    )
    if ready:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "gateway_rule": RULE_NAME,
                    "gateway_port": int(port),
                    "discovery_rule": DISCOVERY_RULE_NAME,
                    "discovery_port": int(discovery_port),
                    "profiles": "any",
                    "ready": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return True, "already-ready"

    success = (
        _add_rules_direct(port, discovery_port)
        if _is_admin()
        else _add_rules_elevated(port, discovery_port)
    )
    if not success:
        return False, (
            "Windows did not allow the DjGoo gateway and LAN-discovery rules on "
            "all network profiles. Local recipients cannot discover or connect "
            "until the UAC request is approved."
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "gateway_rule": RULE_NAME,
                "gateway_port": int(port),
                "discovery_rule": DISCOVERY_RULE_NAME,
                "discovery_port": int(discovery_port),
                "profiles": "any",
                "ready": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return True, "created"
