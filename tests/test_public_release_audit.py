from __future__ import annotations

from pathlib import Path

from tools.public_release_audit import audit_public_release


REQUIRED = (
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "config/secrets.example.json",
    ".gitignore",
)


def _public_tree(tmp_path: Path) -> tuple[Path, list[str]]:
    for relative in REQUIRED:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == ".gitignore":
            path.write_text(
                "config/secrets.json\ndata/\nlogs/\n.localappdata/\n",
                encoding="utf-8",
            )
        elif relative == "config/secrets.example.json":
            path.write_text(
                '{"webhook_url":"PASTE_NEW_WEBHOOK_URL_HERE"}\n',
                encoding="utf-8",
            )
        else:
            path.write_text("public project file\n", encoding="utf-8")
    return tmp_path, list(REQUIRED)


def test_public_release_audit_accepts_placeholders(tmp_path: Path) -> None:
    root, paths = _public_tree(tmp_path)

    assert audit_public_release(root, paths=paths) == []


def test_public_release_audit_rejects_runtime_secret_file(tmp_path: Path) -> None:
    root, paths = _public_tree(tmp_path)
    secret = root / "config" / "secrets.json"
    secret.write_text('{"bot_token":"not-safe-to-publish"}\n', encoding="utf-8")
    paths.append("config/secrets.json")

    failures = audit_public_release(root, paths=paths)

    assert any("private runtime file is tracked" in item for item in failures)


def test_public_release_audit_rejects_webhook_credentials(tmp_path: Path) -> None:
    root, paths = _public_tree(tmp_path)
    leaked = root / "leaked.txt"
    # Assemble the example so this test file does not itself resemble a secret.
    leaked.write_text(
        "https://discord.com/api/" + "webhooks/123456789012345678/" + "A" * 48,
        encoding="utf-8",
    )
    paths.append("leaked.txt")

    failures = audit_public_release(root, paths=paths)

    assert any("Discord webhook URL" in item for item in failures)


def test_current_repository_passes_public_release_audit() -> None:
    root = Path(__file__).resolve().parents[1]

    assert audit_public_release(root) == []
