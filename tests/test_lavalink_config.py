from pathlib import Path

import yaml

from tools.build_windows_product import build


ROOT = Path(__file__).resolve().parents[1]


def test_bundled_youtube_plugin_replaces_deprecated_source() -> None:
    config = yaml.safe_load((ROOT / "config" / "lavalink.application.yml").read_text())

    assert config["lavalink"]["server"]["sources"]["youtube"] is False
    youtube = config["plugins"]["youtube"]
    assert youtube["enabled"] is True
    assert youtube["allowSearch"] is True
    assert "TVHTML5_SIMPLY" in youtube["clients"]
    assert youtube["remoteCipher"]["url"] == "https://cipher.kikkia.dev/"


def test_product_builder_bundles_youtube_plugin(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    for name in ("python", "java", "webrtc"):
        (source / name).mkdir(parents=True)
        (source / name / "payload").write_text(name)
    lavalink = source / "Lavalink.jar"
    lavalink.write_bytes(b"lavalink")
    plugin = source / "youtube-plugin-1.18.2.jar"
    plugin.write_bytes(b"youtube-plugin")

    def fake_app(path, *_):
        path.mkdir(parents=True)
        (path / "payload").write_text("app")
        return path
    monkeypatch.setattr("tools.build_windows_product.build_app_layer", fake_app)

    from argparse import Namespace
    args = Namespace(
        output=tmp_path / "out", version="test", python=source / "python", voice_python=None,
        java=source / "java", webrtc=source / "webrtc", lavalink=lavalink,
        youtube_plugin=plugin, python_generation="p", java_generation="j",
        webrtc_generation="w", lavalink_generation="l",
    )
    # Native publication is covered by the Windows product tests; prepare its expected output.
    def fake_publish(_project, output):
        output.mkdir(parents=True, exist_ok=True)
        exe = output / "artifact.exe"
        exe.write_bytes(b"exe")
        return exe
    monkeypatch.setattr("tools.build_windows_product.publish", fake_publish)
    result = build(args)

    assert (result / "layers/lavalink/l/plugins/youtube-plugin-1.18.2.jar").read_bytes() == b"youtube-plugin"
