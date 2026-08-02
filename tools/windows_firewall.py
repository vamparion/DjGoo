from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from voice.lan_discovery import DISCOVERY_PORT


RULE_NAME = "DjGoo Voice Gateway"
DISCOVERY_RULE_NAME = "DjGoo Voice Discovery"
RECIPIENT_DISCOVERY_RULE_NAME = "DjGoo Voice Remote Discovery Outbound"
RECIPIENT_GATEWAY_RULE_NAME = "DjGoo Voice Remote Gateway Outbound"


@dataclass(frozen=True)
class FirewallRuleSpec:
    name: str
    direction: str
    protocol: str
    port: int
    port_field: str
    program: str | None = None

    @property
    def normalized_direction(self) -> str:
        return "out" if self.direction.strip().lower().startswith("out") else "in"

    @property
    def normalized_protocol(self) -> str:
        return self.protocol.strip().lower()


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _powershell_executable() -> str:
    return "powershell.exe" if os.name == "nt" else "powershell"


def _powershell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )


def _firewall_enabled() -> bool | None:
    """Return whether any Windows Firewall profile is enabled.

    ``None`` means the state could not be queried. In that case DjGoo attempts
    normal rule repair instead of incorrectly assuming the firewall is off.
    """

    if os.name != "nt":
        return False
    script = (
        "$ErrorActionPreference='Stop';"
        "$enabled=@(Get-NetFirewallProfile | Where-Object {$_.Enabled});"
        "if($enabled.Count -gt 0){Write-Output 'enabled'}else{Write-Output 'disabled'}"
    )
    try:
        result = _run_powershell(script)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip().lower()
    if value == "enabled":
        return True
    if value == "disabled":
        return False
    return None


def _netsh_field(output: str, name: str) -> str:
    expected = name.strip().lower()
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == expected:
            return value.strip().lower()
    return ""


def _field_tokens(value: object) -> set[str]:
    text = str(value or "")
    return {
        item.strip().lower()
        for item in text.replace(";", ",").replace(" ", ",").split(",")
        if item.strip()
    }


def _all_profiles(value: object) -> bool:
    profiles = _field_tokens(value)
    return bool(
        "any" in profiles
        or "all" in profiles
        or {"domain", "private", "public"}.issubset(profiles)
    )


def _normalize_program(value: object) -> str:
    text = str(value or "").strip().strip('"')
    if text.lower() in {"", "any", "notconfigured"}:
        return ""
    try:
        return os.path.normcase(os.path.abspath(text))
    except (OSError, ValueError):
        return os.path.normcase(text)


def _powershell_rule_records(rule_name: str) -> list[dict[str, Any]] | None:
    """Read firewall rule metadata without depending on localized netsh labels."""

    name = _powershell_quote(rule_name)
    script = (
        "$ErrorActionPreference='Stop';"
        f"$rules=@(Get-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue);"
        "$items=@();"
        "foreach($rule in $rules){"
        "$port=$rule|Get-NetFirewallPortFilter;"
        "$app=$rule|Get-NetFirewallApplicationFilter;"
        "$items+=[pscustomobject]@{"
        "Enabled=[string]$rule.Enabled;"
        "Direction=[string]$rule.Direction;"
        "Action=[string]$rule.Action;"
        "Profile=[string]$rule.Profile;"
        "Protocol=[string]$port.Protocol;"
        "LocalPort=[string]$port.LocalPort;"
        "RemotePort=[string]$port.RemotePort;"
        "Program=[string]$app.Program"
        "};"
        "};"
        "@($items)|ConvertTo-Json -Compress"
    )
    try:
        result = _run_powershell(script)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    if not output:
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return None


def _record_matches(record: dict[str, Any], spec: FirewallRuleSpec) -> bool:
    enabled = str(record.get("Enabled") or "").strip().lower()
    direction = str(record.get("Direction") or "").strip().lower()
    action = str(record.get("Action") or "").strip().lower()
    protocol = str(record.get("Protocol") or "").strip().lower()
    expected_protocols = {
        "tcp": {"tcp", "6"},
        "udp": {"udp", "17"},
    }.get(spec.normalized_protocol, {spec.normalized_protocol})
    expected_directions = (
        {"out", "outbound"}
        if spec.normalized_direction == "out"
        else {"in", "inbound"}
    )
    port_key = "RemotePort" if spec.port_field.lower() == "remoteport" else "LocalPort"
    ports = _field_tokens(record.get(port_key))
    if not (
        enabled in {"true", "yes", "1"}
        and direction in expected_directions
        and action == "allow"
        and protocol in expected_protocols
        and str(int(spec.port)) in ports
        and _all_profiles(record.get("Profile"))
    ):
        return False
    if spec.program:
        return _normalize_program(record.get("Program")) == _normalize_program(spec.program)
    return True


def _netsh_rule_ready(spec: FirewallRuleSpec) -> bool:
    result = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={spec.name}",
            "verbose",
        ],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    direction = _netsh_field(output, "direction")
    expected_directions = (
        {"out", "outbound"}
        if spec.normalized_direction == "out"
        else {"in", "inbound"}
    )
    protocol = _netsh_field(output, "protocol")
    expected_protocols = {
        "tcp": {"tcp", "6"},
        "udp": {"udp", "17"},
    }.get(spec.normalized_protocol, {spec.normalized_protocol})
    port_name = "remoteport" if spec.port_field.lower() == "remoteport" else "localport"
    ports = _field_tokens(_netsh_field(output, port_name))
    ready = bool(
        result.returncode == 0
        and _netsh_field(output, "enabled") in {"yes", "true"}
        and direction in expected_directions
        and _netsh_field(output, "action") == "allow"
        and protocol in expected_protocols
        and str(int(spec.port)) in ports
        and _all_profiles(_netsh_field(output, "profiles"))
    )
    if ready and spec.program:
        return _normalize_program(_netsh_field(output, "program")) == _normalize_program(spec.program)
    return ready


def _rule_ready(spec: FirewallRuleSpec) -> bool:
    if os.name != "nt":
        return True
    records = _powershell_rule_records(spec.name)
    if records is not None:
        return any(_record_matches(record, spec) for record in records)
    return _netsh_rule_ready(spec)


def _host_gateway_spec(port: int) -> FirewallRuleSpec:
    return FirewallRuleSpec(RULE_NAME, "in", "tcp", int(port), "localport")


def _host_discovery_spec(port: int) -> FirewallRuleSpec:
    return FirewallRuleSpec(
        DISCOVERY_RULE_NAME,
        "in",
        "udp",
        int(port),
        "localport",
    )


def _recipient_discovery_spec(port: int, program: str) -> FirewallRuleSpec:
    return FirewallRuleSpec(
        RECIPIENT_DISCOVERY_RULE_NAME,
        "out",
        "udp",
        int(port),
        "remoteport",
        program,
    )


def _recipient_gateway_spec(port: int, program: str) -> FirewallRuleSpec:
    return FirewallRuleSpec(
        RECIPIENT_GATEWAY_RULE_NAME,
        "out",
        "tcp",
        int(port),
        "remoteport",
        program,
    )


def firewall_rule_ready(port: int = 47632) -> bool:
    return _rule_ready(_host_gateway_spec(port))


def discovery_firewall_rule_ready(port: int = DISCOVERY_PORT) -> bool:
    return _rule_ready(_host_discovery_spec(port))


def recipient_firewall_rules_ready(
    executable: Path,
    *,
    gateway_port: int = 47632,
    discovery_port: int = DISCOVERY_PORT,
) -> bool:
    program = str(executable.resolve())
    return bool(
        _rule_ready(_recipient_discovery_spec(discovery_port, program))
        and _rule_ready(_recipient_gateway_spec(gateway_port, program))
    )


def _rule_arguments(spec: FirewallRuleSpec) -> list[str]:
    arguments = [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={spec.name}",
        f"dir={spec.normalized_direction}",
        "action=allow",
        f"protocol={spec.protocol.upper()}",
        f"{spec.port_field.lower()}={int(spec.port)}",
        "profile=any",
        "enable=yes",
    ]
    if spec.program:
        arguments.append(f"program={spec.program}")
    return arguments


def _netsh_arguments(port: int) -> list[str]:
    return _rule_arguments(_host_gateway_spec(port))


def _discovery_netsh_arguments(port: int) -> list[str]:
    return _rule_arguments(_host_discovery_spec(port))


def _recipient_discovery_netsh_arguments(port: int, program: str) -> list[str]:
    return _rule_arguments(_recipient_discovery_spec(port, program))


def _recipient_gateway_netsh_arguments(port: int, program: str) -> list[str]:
    return _rule_arguments(_recipient_gateway_spec(port, program))


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


def _add_rule(spec: FirewallRuleSpec) -> bool:
    result = subprocess.run(
        ["netsh", *_rule_arguments(spec)],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    return result.returncode == 0


def _rules_ready(specs: tuple[FirewallRuleSpec, ...]) -> bool:
    return all(_rule_ready(spec) for spec in specs)


def _add_rules_direct(specs: tuple[FirewallRuleSpec, ...]) -> bool:
    for spec in specs:
        _delete_rule(spec.name)
    for spec in specs:
        if not _add_rule(spec):
            return False
    return _rules_ready(specs)


def _add_rules_elevated(specs: tuple[FirewallRuleSpec, ...]) -> bool:
    commands: list[str] = []
    for spec in specs:
        commands.append(
            subprocess.list2cmdline(
                [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "delete",
                    "rule",
                    f"name={spec.name}",
                ]
            )
        )
    for spec in specs:
        commands.append(subprocess.list2cmdline(["netsh", *_rule_arguments(spec)]))
        commands.append("if errorlevel 1 exit /b %errorlevel%")

    path = Path(tempfile.gettempdir()) / (
        f"djgoo-firewall-{os.getpid()}-{time.time_ns()}.cmd"
    )
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
            if _rules_ready(specs):
                return True
            time.sleep(0.5)
        return False
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _write_marker(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _ensure_rules(
    *,
    specs: tuple[FirewallRuleSpec, ...],
    marker: Path,
    marker_payload: dict[str, object],
    failure_message: str,
) -> tuple[bool, str]:
    if os.name != "nt":
        return True, "not-windows"
    firewall_enabled = _firewall_enabled()
    if firewall_enabled is False:
        _write_marker(marker, {**marker_payload, "ready": True, "firewall": "disabled"})
        return True, "firewall-disabled"
    if _rules_ready(specs):
        _write_marker(marker, {**marker_payload, "ready": True})
        return True, "already-ready"
    success = _add_rules_direct(specs) if _is_admin() else _add_rules_elevated(specs)
    if not success:
        return False, failure_message
    _write_marker(marker, {**marker_payload, "ready": True})
    return True, "created"


def ensure_gateway_firewall(
    project_root: Path,
    *,
    port: int = 47632,
    discovery_port: int = DISCOVERY_PORT,
) -> tuple[bool, str]:
    """Allow Host gateway TCP and pinned LAN discovery UDP on all profiles."""

    specs = (
        _host_gateway_spec(port),
        _host_discovery_spec(discovery_port),
    )
    return _ensure_rules(
        specs=specs,
        marker=project_root / "data" / "gateway-firewall.json",
        marker_payload={
            "scope": "host",
            "gateway_rule": RULE_NAME,
            "gateway_port": int(port),
            "discovery_rule": DISCOVERY_RULE_NAME,
            "discovery_port": int(discovery_port),
            "profiles": "any",
        },
        failure_message=(
            "Windows did not allow the DjGoo Host gateway and LAN-discovery "
            "rules on all network profiles. Local recipients cannot discover "
            "or connect until the UAC request is approved."
        ),
    )


def ensure_recipient_firewall(
    project_root: Path,
    executable: Path | None,
    *,
    gateway_port: int = 47632,
    discovery_port: int = DISCOVERY_PORT,
) -> tuple[bool, str]:
    """Allow only DjGoo Voice's outbound discovery and gateway traffic.

    Windows Firewall is stateful, so replies to the recipient's UDP discovery
    request are permitted by the outbound flow. Opening a broad inbound port on
    recipient computers would add risk without fixing the connection path.
    """

    if os.name != "nt":
        return True, "not-windows"
    if executable is None or not executable.exists():
        return True, "source-mode"
    program = str(executable.resolve())
    specs = (
        _recipient_discovery_spec(discovery_port, program),
        _recipient_gateway_spec(gateway_port, program),
    )
    return _ensure_rules(
        specs=specs,
        marker=project_root / "data" / "voice-firewall.json",
        marker_payload={
            "scope": "recipient",
            "program": program,
            "discovery_rule": RECIPIENT_DISCOVERY_RULE_NAME,
            "discovery_remote_port": int(discovery_port),
            "gateway_rule": RECIPIENT_GATEWAY_RULE_NAME,
            "gateway_remote_port": int(gateway_port),
            "profiles": "any",
            "direction": "outbound",
        },
        failure_message=(
            "Windows did not allow DjGoo Voice's outbound LAN-discovery and "
            "gateway rules. Pairing can still use an internet fallback, but "
            "local discovery may fail until the UAC request is approved."
        ),
    )
