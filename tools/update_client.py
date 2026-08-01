from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping


OWNER = "vamparion"
REPOSITORY = "DjGoo"
API_VERSION = "2022-11-28"
RELEASES_API = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases?per_page=30"
MANIFEST_ASSET_NAME = "DjGoo-Host-update.json"
BUNDLE_ASSET_NAME = "DjGoo-Host-update.zip"
USER_AGENT = "DjGoo-Updater/1"
VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<channel>alpha|beta|rc)\.(?P<number>\d+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$",
    re.IGNORECASE,
)


class UpdateError(RuntimeError):
    pass


class AuthenticationRequired(UpdateError):
    pass


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int
    channel_rank: int
    channel_number: int
    text: str

    @property
    def is_prerelease(self) -> bool:
        return self.channel_rank < 3


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    api_url: str
    size: int
    digest: str | None = None


@dataclass(frozen=True)
class UpdateOffer:
    tag: str
    version: Version
    release_name: str
    published_at: str
    manifest_asset: ReleaseAsset
    bundle_asset: ReleaseAsset


ProgressCallback = Callable[[int, int], None]


def parse_version(value: str) -> Version | None:
    text = str(value or "").strip()
    match = VERSION_PATTERN.fullmatch(text)
    if not match:
        return None
    channel = (match.group("channel") or "").lower()
    rank = {"alpha": 0, "beta": 1, "rc": 2, "": 3}[channel]
    number = int(match.group("number") or 0)
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        channel_rank=rank,
        channel_number=number,
        text=text.lstrip("v"),
    )


def read_installed_version(project_root: Path) -> Version:
    root = project_root.resolve()
    candidates = (root / "data" / "installed-version.json", root / "manifest.json")
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = parse_version(str(payload.get("version") or "")) if isinstance(payload, dict) else None
        if version is not None:
            return version
    return Version(0, 0, 0, 0, 0, "0.0.0-alpha.0")


def _headers(token: str | None, *, binary: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _open(url: str, token: str | None, *, binary: bool = False, timeout: int = 30):
    request = urllib.request.Request(url, headers=_headers(token, binary=binary))
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise AuthenticationRequired(
                "GitHub could not authorize access to DjGoo's private release assets."
            ) from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code} while checking for updates") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Could not reach GitHub: {exc.reason}") from exc


def fetch_releases(token: str | None = None) -> list[dict[str, object]]:
    with _open(RELEASES_API, token) as response:
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub returned an invalid release response") from exc
    if not isinstance(payload, list):
        raise UpdateError("GitHub returned an unexpected release response")
    return [item for item in payload if isinstance(item, dict)]


def _asset_map(release: Mapping[str, object]) -> dict[str, ReleaseAsset]:
    result: dict[str, ReleaseAsset] = {}
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        return result
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        api_url = str(item.get("url") or "").strip()
        if not name or not api_url:
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digest_text = str(item.get("digest") or "").strip()
        result[name] = ReleaseAsset(
            name=name,
            api_url=api_url,
            size=max(size, 0),
            digest=digest_text or None,
        )
    return result


def select_update(
    releases: Iterable[Mapping[str, object]],
    installed: Version,
    *,
    include_prereleases: bool | None = None,
) -> UpdateOffer | None:
    allow_prereleases = installed.is_prerelease if include_prereleases is None else include_prereleases
    candidates: list[UpdateOffer] = []
    for release in releases:
        if bool(release.get("draft")):
            continue
        if bool(release.get("prerelease")) and not allow_prereleases:
            continue
        tag = str(release.get("tag_name") or "").strip()
        version = parse_version(tag)
        if version is None or version <= installed:
            continue
        assets = _asset_map(release)
        manifest_asset = assets.get(MANIFEST_ASSET_NAME)
        bundle_asset = assets.get(BUNDLE_ASSET_NAME)
        if manifest_asset is None or bundle_asset is None:
            continue
        candidates.append(
            UpdateOffer(
                tag=tag,
                version=version,
                release_name=str(release.get("name") or tag),
                published_at=str(release.get("published_at") or ""),
                manifest_asset=manifest_asset,
                bundle_asset=bundle_asset,
            )
        )
    return max(candidates, key=lambda item: item.version) if candidates else None


def check_for_update(project_root: Path, token: str | None = None) -> UpdateOffer | None:
    installed = read_installed_version(project_root)
    return select_update(fetch_releases(token), installed)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_asset(
    asset: ReleaseAsset,
    destination: Path,
    token: str | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    downloaded = 0
    try:
        with _open(asset.api_url, token, binary=True, timeout=60) as response, temporary.open("wb") as output:
            header_size = response.headers.get("Content-Length")
            try:
                total = int(header_size) if header_size else asset.size
            except ValueError:
                total = asset.size
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                downloaded += len(block)
                if progress is not None:
                    progress(downloaded, max(total, asset.size, 0))
        if asset.size and downloaded != asset.size:
            raise UpdateError(
                f"Downloaded {downloaded} bytes for {asset.name}; GitHub reported {asset.size}."
            )
        os.replace(temporary, destination)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return destination


def validate_manifest(payload: object, offer: UpdateOffer) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise UpdateError("The update manifest is not a JSON object")
    try:
        schema = int(payload.get("schema", 0))
    except (TypeError, ValueError):
        schema = 0
    if schema != 1:
        raise UpdateError(f"Unsupported update manifest schema: {schema}")
    if str(payload.get("product") or "") != "DjGoo Host":
        raise UpdateError("The update manifest is for a different product")
    if str(payload.get("release_tag") or "") != offer.tag:
        raise UpdateError("The update manifest tag does not match the selected release")
    if str(payload.get("bundle_asset") or "") != BUNDLE_ASSET_NAME:
        raise UpdateError("The update manifest references an unexpected bundle")
    manifest_version = parse_version(str(payload.get("version") or ""))
    if manifest_version is None or manifest_version != offer.version:
        raise UpdateError("The update manifest version does not match the selected release")
    bundle_hash = str(payload.get("bundle_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", bundle_hash):
        raise UpdateError("The update manifest has an invalid bundle SHA-256")
    try:
        bundle_size = int(payload.get("bundle_size") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError("The update manifest has an invalid bundle size") from exc
    if bundle_size <= 0:
        raise UpdateError("The update manifest has an invalid bundle size")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateError("The update manifest does not list any files")
    return dict(payload)


def download_update(
    project_root: Path,
    offer: UpdateOffer,
    token: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    updates_dir = project_root.resolve() / "data" / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    safe_tag = re.sub(r"[^0-9A-Za-z._-]+", "-", offer.tag)
    manifest_path = updates_dir / f"{safe_tag}-{MANIFEST_ASSET_NAME}"
    bundle_path = updates_dir / f"{safe_tag}-{BUNDLE_ASSET_NAME}"

    download_asset(offer.manifest_asset, manifest_path, token)
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The downloaded update manifest is invalid") from exc
    manifest = validate_manifest(manifest_payload, offer)

    download_asset(offer.bundle_asset, bundle_path, token, progress)
    actual_size = bundle_path.stat().st_size
    expected_size = int(manifest["bundle_size"])
    if actual_size != expected_size:
        raise UpdateError(
            f"Update bundle size mismatch: expected {expected_size}, downloaded {actual_size}."
        )
    actual_hash = _sha256(bundle_path)
    expected_hash = str(manifest["bundle_sha256"]).lower()
    if actual_hash != expected_hash:
        raise UpdateError("Update bundle SHA-256 verification failed")
    return bundle_path, manifest_path, manifest
