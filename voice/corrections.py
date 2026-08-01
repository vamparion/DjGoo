from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CORRECTIONS_PATH = Path("data/voice-corrections.json")


def load_corrections(project_root: Path, configured: Any = None) -> dict[str, str]:
    corrections: dict[str, str] = {}
    path = project_root / DEFAULT_CORRECTIONS_PATH

    if isinstance(configured, str) and configured.strip():
        configured_path = Path(configured)
        path = configured_path if configured_path.is_absolute() else project_root / configured_path
    elif isinstance(configured, Mapping):
        corrections.update(_clean_mapping(configured))

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, Mapping):
            raw = data.get("corrections", data)
            if isinstance(raw, Mapping):
                corrections.update(_clean_mapping(raw))
    return corrections


def apply_corrections(text: str, corrections: Mapping[str, str]) -> str:
    corrected = text
    for heard, intended in sorted(corrections.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(heard)}(?!\w)", re.IGNORECASE)
        corrected = pattern.sub(intended, corrected)
    return re.sub(r"\s+", " ", corrected).strip()


def correction_hotwords(corrections: Mapping[str, str]) -> str:
    values = [value.strip() for value in corrections.values() if value.strip()]
    return " ".join(dict.fromkeys(values))


def _clean_mapping(mapping: Mapping[Any, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in mapping.items():
        heard = str(key).strip()
        intended = str(value).strip()
        if heard and intended:
            result[heard] = intended
    return result
