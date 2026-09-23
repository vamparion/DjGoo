from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


CURRENT_FILE = "current.json"
APP_DIRECTORY = "app"
RUNTIME_DIRECTORY = "runtime"
SCHEMA = 1


class AppLayoutError(RuntimeError):
    pass


def package_root(fallback: Path | None = None) -> Path:
    configured = str(os.environ.get("DJGOO_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if fallback is not None:
        return fallback.resolve()
    return Path.cwd().resolve()


def _safe_child(root: Path, relative: str) -> Path:
    text = str(relative or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or ":" in text.split("/", 1)[0]:
        raise AppLayoutError(f"Invalid DjGoo application path: {relative!r}")
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise AppLayoutError(f"DjGoo application path escapes package root: {relative!r}") from exc
    return candidate


def read_current(root: Path) -> dict[str, object] | None:
    path = root.resolve() / CURRENT_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("schema", 0)) != SCHEMA:
        return None
    return payload


def active_app_root(
    root: Path,
    *,
    require: bool = False,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the active application layer for one package root.

    ``environment`` is explicit for subprocess construction. When a caller is
    building an environment from a supplied mapping, process-global variables
    from another DjGoo instance or test must not leak into that result.
    """

    root = root.resolve()
    source = os.environ if environment is None else environment
    configured = str(source.get("DJGOO_APP_ROOT") or "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise AppLayoutError("DJGOO_APP_ROOT is outside the DjGoo package") from exc
        if candidate.is_dir() or not require:
            return candidate

    current = read_current(root)
    if current is not None:
        candidate = _safe_child(root, str(current.get("path") or ""))
        if candidate.is_dir() or not require:
            return candidate

    # Alpha.24 and older installations keep application files at package root.
    if require and not root.is_dir():
        raise AppLayoutError(f"DjGoo package root does not exist: {root}")
    return root


def current_payload(version: str, app_relative_path: str | None = None) -> dict[str, object]:
    normalized = str(version).strip().lstrip("v")
    if not normalized:
        raise AppLayoutError("DjGoo version is empty")
    relative = app_relative_path or f"{APP_DIRECTORY}/{normalized}"
    if relative.replace("\\", "/").startswith("/"):
        raise AppLayoutError("DjGoo application path must be relative")
    return {
        "schema": SCHEMA,
        "version": normalized,
        "path": relative.replace("\\", "/"),
    }


def write_current(root: Path, version: str, app_relative_path: str | None = None) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / CURRENT_FILE
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(current_payload(version, app_relative_path), indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def runtime_python_candidates(root: Path, product: str) -> tuple[Path, ...]:
    root = root.resolve()
    normalized = product.strip().lower()
    preferred = "python-voice" if normalized in {"voice", "recipient"} else "python-bot"
    return (
        root / RUNTIME_DIRECTORY / preferred / "python.exe",
        root / RUNTIME_DIRECTORY / "python" / "python.exe",
        root / ".voice-venv" / "Scripts" / "python.exe"
        if preferred == "python-voice"
        else root / ".venv" / "Scripts" / "python.exe",
    )


def runtime_python(root: Path, product: str, *, windowed: bool = False) -> Path:
    candidates = list(runtime_python_candidates(root, product))
    if windowed:
        candidates = [path.with_name("pythonw.exe") for path in candidates] + candidates
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def speech_site_packages(root: Path) -> Path:
    return root.resolve() / RUNTIME_DIRECTORY / "speech" / "Lib" / "site-packages"


def webrtc_site_packages(root: Path) -> Path:
    return root.resolve() / RUNTIME_DIRECTORY / "webrtc" / "Lib" / "site-packages"


def speech_runtime_ready(root: Path) -> bool:
    site_packages = speech_site_packages(root)
    return bool(
        site_packages.is_dir()
        and (site_packages / "faster_whisper").is_dir()
        and any(site_packages.glob("ctranslate2*"))
    )


def layered_environment(
    root: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    root = root.resolve()
    env = dict(os.environ if base is None else base)
    app_root = active_app_root(root, environment=env)
    env["DJGOO_HOME"] = str(root)
    env["DJGOO_APP_ROOT"] = str(app_root)

    python_paths = [str(app_root)]
    webrtc = webrtc_site_packages(root)
    if webrtc.is_dir():
        python_paths.append(str(webrtc))
    speech = speech_site_packages(root)
    if speech.is_dir():
        python_paths.append(str(speech))
    existing = str(env.get("PYTHONPATH") or "").strip()
    if existing:
        python_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env
