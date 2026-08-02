from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tools.windows_firewall as windows_firewall


def _result(output: str, returncode: int = 0):
    return SimpleNamespace(
        stdout=output,
        stderr="",
        returncode=returncode,
    )


def test_firewall_rule_requires_public_profile(monkeypatch) -> None:
    monkeypatch.setattr(windows_firewall.os, "name", "nt")
    private_only = """
Rule Name: DjGoo Voice Gateway
Enabled: Yes
Direction: In
Profiles: Domain,Private
Action: Allow
Protocol: TCP
LocalPort: 47632
"""
    monkeypatch.setattr(
        windows_firewall.subprocess,
        "run",
        lambda *args, **kwargs: _result(private_only),
    )

    assert windows_firewall.firewall_rule_ready(47632) is False


def test_firewall_rule_accepts_all_profiles(monkeypatch) -> None:
    monkeypatch.setattr(windows_firewall.os, "name", "nt")
    all_profiles = """
Rule Name: DjGoo Voice Gateway
Enabled: Yes
Direction: In
Profiles: Domain,Private,Public
Action: Allow
Protocol: TCP
LocalPort: 47632
"""
    monkeypatch.setattr(
        windows_firewall.subprocess,
        "run",
        lambda *args, **kwargs: _result(all_profiles),
    )

    assert windows_firewall.firewall_rule_ready(47632) is True


def test_discovery_rule_requires_udp(monkeypatch) -> None:
    monkeypatch.setattr(windows_firewall.os, "name", "nt")
    udp_rule = """
Rule Name: DjGoo Voice Discovery
Enabled: Yes
Direction: In
Profiles: Domain,Private,Public
Action: Allow
Protocol: UDP
LocalPort: 47631
"""
    monkeypatch.setattr(
        windows_firewall.subprocess,
        "run",
        lambda *args, **kwargs: _result(udp_rule),
    )

    assert windows_firewall.discovery_firewall_rule_ready(47631) is True


def test_new_host_firewall_rules_target_every_profile() -> None:
    assert "profile=any" in windows_firewall._netsh_arguments(47632)
    discovery = windows_firewall._discovery_netsh_arguments(47631)
    assert "profile=any" in discovery
    assert "dir=in" in discovery
    assert "protocol=UDP" in discovery
    assert "localport=47631" in discovery


def test_recipient_rules_are_outbound_and_program_scoped(tmp_path: Path) -> None:
    executable = tmp_path / "DjGoo Voice.exe"
    executable.write_bytes(b"test")
    program = str(executable.resolve())

    discovery = windows_firewall._recipient_discovery_netsh_arguments(
        47631,
        program,
    )
    gateway = windows_firewall._recipient_gateway_netsh_arguments(
        47632,
        program,
    )

    assert "dir=out" in discovery
    assert "protocol=UDP" in discovery
    assert "remoteport=47631" in discovery
    assert f"program={program}" in discovery
    assert "profile=any" in discovery

    assert "dir=out" in gateway
    assert "protocol=TCP" in gateway
    assert "remoteport=47632" in gateway
    assert f"program={program}" in gateway
    assert "profile=any" in gateway


def test_recipient_rule_record_requires_exact_program(tmp_path: Path) -> None:
    executable = tmp_path / "DjGoo Voice.exe"
    executable.write_bytes(b"test")
    spec = windows_firewall._recipient_gateway_spec(
        47632,
        str(executable.resolve()),
    )
    record = {
        "Enabled": "True",
        "Direction": "Outbound",
        "Action": "Allow",
        "Profile": "Any",
        "Protocol": "TCP",
        "LocalPort": "Any",
        "RemotePort": "47632",
        "Program": str(executable.resolve()),
    }

    assert windows_firewall._record_matches(record, spec) is True
    record["Program"] = str(tmp_path / "Other.exe")
    assert windows_firewall._record_matches(record, spec) is False


def test_disabled_firewall_does_not_request_elevation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(windows_firewall.os, "name", "nt")
    monkeypatch.setattr(windows_firewall, "_firewall_enabled", lambda: False)
    monkeypatch.setattr(
        windows_firewall,
        "_add_rules_elevated",
        lambda specs: (_ for _ in ()).throw(AssertionError("should not elevate")),
    )

    success, detail = windows_firewall.ensure_gateway_firewall(tmp_path)

    assert success is True
    assert detail == "firewall-disabled"
    marker = tmp_path / "data" / "gateway-firewall.json"
    assert marker.exists()
