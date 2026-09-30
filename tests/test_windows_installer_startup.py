from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_replaces_legacy_source_startup_with_native_product() -> None:
    script = (ROOT / "installer" / "DjGoo.iss").read_text(encoding="utf-8")

    assert 'ValueName: "DjGoo"' in script
    assert 'ValueData: """{app}\\DjGoo.exe"""' in script
    assert 'Parameters: "/Delete /TN ""DjGoo Startup"" /F"' in script
    assert ".venv" not in script
    assert "powershell" not in script.lower()
