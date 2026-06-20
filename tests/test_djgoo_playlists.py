import tempfile
import unittest
from pathlib import Path

from voice.djgoo_playlists import DjGooPlaylists


class DjGooPlaylistsTests(unittest.TestCase):
    def test_add_track_uses_simple_fuzzy_playlist_names_and_dedupes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DjGooPlaylists(Path(temp_dir) / "playlists.json")
            first = store.add_track(
                "white girl",
                {"title": "Call Me Maybe", "uri": "https://youtu.be/fWNaR-rxAic"},
            )
            second = store.add_track(
                "white girl music",
                {"title": "Call Me Maybe", "uri": "https://youtu.be/fWNaR-rxAic"},
            )

            self.assertTrue(first.added)
            self.assertFalse(second.added)
            self.assertEqual(second.playlist_name, "white girl")
            self.assertEqual(store.get_tracks("white girl music")[0]["title"], "Call Me Maybe")

    def test_get_tracks_returns_empty_for_missing_playlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DjGooPlaylists(Path(temp_dir) / "playlists.json")

            self.assertEqual(store.get_tracks("edm"), [])


if __name__ == "__main__":
    unittest.main()
