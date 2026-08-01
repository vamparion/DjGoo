from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path


def component_for_distribution(distribution: importlib.metadata.Distribution) -> dict[str, object]:
    metadata = distribution.metadata
    name = str(metadata.get("Name") or "unknown")
    version = str(metadata.get("Version") or "unknown")
    license_value = str(metadata.get("License") or "NOASSERTION")
    return {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
        "licenses": [{"license": {"name": license_value}}],
    }


def generate(site_packages: Path, output: Path, application_version: str) -> None:
    distributions = sorted(
        importlib.metadata.distributions(path=[str(site_packages)]),
        key=lambda item: str(item.metadata.get("Name") or "").lower(),
    )
    components = [component_for_distribution(item) for item in distributions]
    serial_seed = json.dumps(components, sort_keys=True).encode("utf-8")
    serial = hashlib.sha256(serial_seed).hexdigest()
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial[0:8]}-{serial[8:12]}-{serial[12:16]}-{serial[16:20]}-{serial[20:32]}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "DjGoo Host",
                "version": application_version,
                "licenses": [{"license": {"id": "GPL-3.0-or-later"}}],
            }
        },
        "components": components,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a CycloneDX SBOM for a portable Python runtime.")
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate(args.site_packages.resolve(), args.output.resolve(), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
