import io
import pytest
from unittest.mock import patch

from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge
from local_cogs.djgoowelcome.enhanced_audio_bridge import EnhancedDjGooAudioBridge


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_installed_search_returns_concrete_soundcloud_url() -> None:
    body = b'{"loadType":"SEARCH_RESULT","tracks":[{"info":{"uri":"https://soundcloud.com/darude/sandstorm-radio-edit"}}]}'
    with patch("local_cogs.djgoowelcome.audio_bridge.urlopen", return_value=Response(body)) as open_url:
        resolved = DjGooAudioBridge._soundcloud_search_query("Darude Sandstorm")

    assert resolved == "https://soundcloud.com/darude/sandstorm-radio-edit"
    request = open_url.call_args.args[0]
    assert "scsearch%3ADarude%20Sandstorm" in request.full_url
    assert request.headers["Authorization"] == "youshallnotpass"


def test_direct_media_query_returns_extracted_stream(tmp_path) -> None:
    class Extractor:
        def __init__(self, options):
            assert options["format"] == "bestaudio"
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def extract_info(self, uri, download):
            assert uri == "https://www.youtube.com/watch?v=track"
            if download:
                path = self.options["outtmpl"].replace("%(ext)s", "webm")
                __import__("pathlib").Path(path).write_bytes(b"audio")
            return {
                "ext": "webm",
                "title": "Darude - Sandstorm",
                "uploader": "Darude",
                "duration": 225,
                "thumbnail": "https://img.test/sandstorm.jpg",
                "webpage_url": uri,
            }

        def prepare_filename(self, _info):
            return self.options["outtmpl"].replace("%(ext)s", "webm")

    with patch("yt_dlp.YoutubeDL", Extractor), patch.dict("os.environ", {"DJGOO_DATA_ROOT": str(tmp_path)}, clear=False):
        resolved = DjGooAudioBridge._direct_media_query("https://www.youtube.com/watch?v=track")

    assert resolved and resolved.startswith("localtracks/") and resolved.endswith(".webm")
    metadata = __import__("json").loads((tmp_path / "cache" / "localtracks" / "metadata.json").read_text())
    assert metadata[resolved.removeprefix("localtracks/")]["title"] == "Darude - Sandstorm"


def test_direct_media_query_reuses_verified_cached_source_without_extraction(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    (cache / "track.webm").write_bytes(b"audio")
    (cache / "metadata.json").write_text(
        '{"track.webm":{"source_uri":"https://www.youtube.com/watch?v=track"}}',
        encoding="utf-8",
    )

    with patch("yt_dlp.YoutubeDL", side_effect=AssertionError("cache hit must not invoke yt-dlp")), patch.dict(
        "os.environ", {"DJGOO_DATA_ROOT": str(tmp_path)}, clear=False
    ):
        resolved = DjGooAudioBridge._direct_media_query("https://www.youtube.com/watch?v=track")

    assert resolved == "localtracks/track.webm"


def test_direct_media_query_does_not_reuse_cache_for_another_source(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    (cache / "track.webm").write_bytes(b"audio")
    (cache / "metadata.json").write_text(
        '{"track.webm":{"source_uri":"https://www.youtube.com/watch?v=other"}}',
        encoding="utf-8",
    )

    class Extractor:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def extract_info(self, uri, download):
            assert uri == "https://www.youtube.com/watch?v=track"
            assert download is True
            path = self.options["outtmpl"].replace("%(ext)s", "webm")
            __import__("pathlib").Path(path).write_bytes(b"correct audio")
            return {"ext": "webm", "webpage_url": uri}

        def prepare_filename(self, _info):
            return self.options["outtmpl"].replace("%(ext)s", "webm")

    with patch("yt_dlp.YoutubeDL", Extractor), patch.dict(
        "os.environ", {"DJGOO_DATA_ROOT": str(tmp_path)}, clear=False
    ):
        resolved = DjGooAudioBridge._direct_media_query("https://www.youtube.com/watch?v=track")

    assert resolved != "localtracks/track.webm"


def test_direct_media_query_downloads_stable_local_media_even_when_extractor_has_stream_url(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    (cache / "source-hints.json").write_text(
        '{"https://www.youtube.com/watch?v=track":{"title":"Song","artist":"Correct Artist","duration_seconds":180}}',
        encoding="utf-8",
    )

    class Extractor:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def extract_info(self, uri, download):
            assert download is True
            path = self.options["outtmpl"].replace("%(ext)s", "webm")
            __import__("pathlib").Path(path).write_bytes(b"audio")
            return {
                "ext": "webm",
                "url": "https://media.test/audio?expire=4102444800",
                "webpage_url": uri,
                "title": "Extractor title",
                "uploader": "Extractor artist",
                "duration": 180,
            }

        def prepare_filename(self, _info):
            return self.options["outtmpl"].replace("%(ext)s", "webm")

    with patch("yt_dlp.YoutubeDL", Extractor), patch.dict(
        "os.environ", {"DJGOO_DATA_ROOT": str(tmp_path)}, clear=False
    ):
        first = DjGooAudioBridge._direct_media_query("https://www.youtube.com/watch?v=track")
        second = DjGooAudioBridge._direct_media_query("https://www.youtube.com/watch?v=track")

    assert first == second
    assert first.startswith("localtracks/")
    metadata = __import__("json").loads((cache / "metadata.json").read_text(encoding="utf-8"))
    assert metadata[first.removeprefix("localtracks/")]["artist"] == "Extractor artist"


def test_stream_metadata_uses_find_artist(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    stream = "https://media.test/audio?expire=4102444800"
    (cache / "streams.json").write_text(
        __import__("json").dumps({stream: {"source_uri": "https://youtube.test/watch?v=track", "artist": "Fallback"}}),
        encoding="utf-8",
    )
    (cache / "source-hints.json").write_text(
        '{"https://youtube.test/watch?v=track":{"title":"Song","artist":"Correct Artist","duration_seconds":180}}',
        encoding="utf-8",
    )
    bridge = object.__new__(DjGooAudioBridge)
    bridge.project_root = tmp_path
    track = type("Track", (), {"title": "Unknown title", "author": "Unknown artist", "uri": stream, "info": {}, "length": 0})()

    data = bridge._track_data(track)

    assert data["title"] == "Song"
    assert data["artist"] == "Correct Artist"
    assert data["uri"] == "https://youtube.test/watch?v=track"


def test_source_hint_enriches_original_url_track(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    uri = "https://www.youtube.com/watch?v=FTQbiNvZqaY"
    (cache / "source-hints.json").write_text(
        __import__("json").dumps({uri: {"title": "Africa", "artist": "Toto", "source_uri": uri}}),
        encoding="utf-8",
    )
    bridge = object.__new__(DjGooAudioBridge)
    bridge.project_root = tmp_path
    track = type("Track", (), {"title": "Africa", "author": "Unknown artist", "uri": uri, "info": {}, "length": 0})()

    data = bridge._track_data(track)

    assert data["title"] == "Africa"
    assert data["artist"] == "Toto"


def test_local_media_metadata_replaces_lavalink_unknown_labels(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    (cache / "metadata.json").write_text(
        '{"track.webm":{"title":"Darude - Sandstorm","artist":"Darude","duration_seconds":225,"artwork_url":"https://img.test/sandstorm.jpg"}}',
        encoding="utf-8",
    )
    bridge = object.__new__(DjGooAudioBridge)
    bridge.project_root = tmp_path
    track = type(
        "Track",
        (),
        {
            "title": "Unknown title",
            "author": "Unknown artist",
            "uri": str(cache / "track.webm"),
            "info": {},
            "length": 0,
        },
    )()

    assert bridge._track_data(track) == {
        "title": "Darude - Sandstorm",
        "artist": "Darude",
        "uri": str(cache / "track.webm"),
        "artwork_url": "https://img.test/sandstorm.jpg",
        "duration_seconds": "225",
    }


def test_enhanced_bridge_preserves_resolved_artist_over_unknown_lavalink_label(tmp_path) -> None:
    cache = tmp_path / "cache" / "localtracks"
    cache.mkdir(parents=True)
    (cache / "metadata.json").write_text(
        '{"track.webm":{"title":"Russia Privjet","artist":"Basshunter","duration_seconds":269}}',
        encoding="utf-8",
    )
    bridge = object.__new__(EnhancedDjGooAudioBridge)
    bridge.project_root = tmp_path
    track = type(
        "Track",
        (),
        {
            "title": "Unknown title",
            "author": "Unknown artist",
            "uri": str(cache / "track.webm"),
            "info": {},
            "length": 0,
        },
    )()

    data = bridge._track_data(track)

    assert data["title"] == "Russia Privjet"
    assert data["artist"] == "Basshunter"


@pytest.mark.asyncio
async def test_installed_radio_requires_stable_local_media(monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_NATIVE_HOST", "1")
    bridge = object.__new__(DjGooAudioBridge)
    bridge._direct_media_query = lambda _uri: None

    resolved = await bridge._installed_radio_query(
        "https://www.youtube.com/watch?v=blocked",
        search_hint="Artist Song",
    )

    assert resolved is None


@pytest.mark.asyncio
async def test_installed_radio_uses_resolved_local_media(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DJGOO_NATIVE_HOST", "1")
    bridge = object.__new__(DjGooAudioBridge)
    local_track = tmp_path / "track.webm"
    bridge._direct_media_query = lambda _uri: str(local_track)

    resolved = await bridge._installed_radio_query(
        "https://www.youtube.com/watch?v=ready",
        search_hint="Artist Song",
    )

    assert resolved == str(local_track)


@pytest.mark.asyncio
async def test_installed_explicit_youtube_url_uses_local_media() -> None:
    bridge = object.__new__(DjGooAudioBridge)

    async def clean(_query):
        return ["https://www.youtube.com/watch?v=track"]

    bridge._resolve_youtube_play_query = clean
    bridge._direct_media_query = lambda _uri: "localtracks/track.webm"

    with patch.dict("os.environ", {"DJGOO_NATIVE_HOST": "1"}, clear=False):
        resolved = await bridge._resolve_play_queries("https://youtu.be/track")

    assert resolved == ["localtracks/track.webm"]
