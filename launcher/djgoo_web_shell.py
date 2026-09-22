from __future__ import annotations

import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path


CONTROL_URL = "https://127.0.0.1:8765/?view=compact"
HEALTH_URL = "https://127.0.0.1:8765/api/healthz"


def _browser() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _wait_for_control_panel(timeout: float = 12.0) -> None:
    context = ssl._create_unverified_context()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1.0, context=context) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)


def main() -> int:
    _wait_for_control_panel()
    browser = _browser()
    if browser is None:
        os.startfile(CONTROL_URL)  # type: ignore[attr-defined]
        return 0
    subprocess.Popen(
        [str(browser), f"--app={CONTROL_URL}", "--ignore-certificate-errors"],
        cwd=str(browser.parent),
        close_fds=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
