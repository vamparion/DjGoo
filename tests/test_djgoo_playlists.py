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

    def test_playlist_crud_uses_stable_track_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DjGooPlaylists(Path(temp_dir) / "playlists.json")
            store.add_track("gym", {"title": "One", "uri": "track:one"})
            store.add_track("gym", {"title": "Two", "uri": "track:two"})
            tracks = store.get_tracks("gym")

            old_name, new_name = store.rename("gym", "workout")
            store.reorder_tracks(
                "workout",
                [tracks[1]["id"], tracks[0]["id"]],
            )
            matched, removed = store.remove_tracks(
                "workout",
                [tracks[0]["id"]],
            )

            self.assertEqual((old_name, new_name), ("gym", "workout"))
            self.assertEqual((matched, removed), ("workout", 1))
            self.assertEqual(store.get_tracks("workout")[0]["title"], "Two")
            self.assertEqual(store.delete("workout"), "workout")
            self.assertEqual(store.summaries(), [])

    def test_metadata_cleanup_and_source_replacement_preserve_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DjGooPlaylists(Path(temp_dir) / "playlists.json")
            store.add_track("night", {"title": "One", "uri": "track:one"})
            track = store.get_tracks("night")[0]
            store.update_metadata("night", {"folder": "Sessions", "tags": ["game", "edm"], "description": "Tonight"})
            store.replace_track("night", track["id"], {"title": "One", "artist": "Artist", "uri": "track:new"})
            summary = store.summaries()[0]
            self.assertEqual(summary["folder"], "Sessions")
            self.assertEqual(summary["tracks"][0]["id"], track["id"])
            self.assertEqual(summary["tracks"][0]["uri"], "track:new")


if __name__ == "__main__":
    unittest.main()
