from __future__ import annotations

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


def test_new_firewall_rule_targets_every_profile() -> None:
    assert "profile=any" in windows_firewall._netsh_arguments(47632)
