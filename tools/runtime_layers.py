from __future__ import annotations

import sys
from pathlib import Path

from tools.app_layout import package_root, webrtc_site_packages


def activate_host_webrtc_layer(fallback_root: Path | None = None) -> Path | None:
    """Activate DjGoo's package-owned optional Host WebRTC dependency layer."""

    root = package_root(fallback_root).resolve()
    site_packages = webrtc_site_packages(root).resolve()
    try:
        site_packages.relative_to(root)
    except ValueError:
        return None
    if not site_packages.is_dir():
        return None
    value = str(site_packages)
    if value not in sys.path:
        sys.path.insert(0, value)
    return site_packages
