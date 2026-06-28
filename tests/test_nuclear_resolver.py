import unittest

from voice.nuclear_resolver import NuclearResolver, normalize_nuclear_track


class NuclearResolverTests(unittest.TestCase):
    def test_normalize_track_uses_artists_title_and_duration(self):
        track = normalize_nuclear_track(
            {
                "title": "Digital Love",
                "durationMs": 301000,
                "artists": [{"name": "Daft Punk"}],
            }
        )

        self.assertEqual(track.title, "Digital Love")
        self.assertEqual(track.artists, ["Daft Punk"])
        self.assertEqual(track.duration_seconds, 301)
        self.assertEqual(track.redbot_query(), "Daft Punk - Digital Love official audio")

    def test_rejects_overlong_and_bad_title_tracks(self):
        resolver = NuclearResolver(transport=lambda *_args, **_kwargs: {})

        self.assertFalse(
            resolver.accepts_track(
                normalize_nuclear_track({"title": "Full Album Mix", "durationMs": 300000, "artists": []})
            )
        )
        self.assertFalse(
            resolver.accepts_track(
                normalize_nuclear_track({"title": "Normal Title", "durationMs": 3600000, "artists": []})
            )
        )
        self.assertTrue(
            resolver.accepts_track(
                normalize_nuclear_track({"title": "Normal Title", "durationMs": 240000, "artists": []})
            )
        )

    def test_resolve_track_returns_first_acceptable_track(self):
        def transport(method, params):
            self.assertEqual(method, "Metadata.search")
            return {
                "tracks": [
                    {"title": "Four Hour Mix", "durationMs": 4 * 60 * 60 * 1000, "artists": [{"name": "Uploader"}]},
                    {"title": "Sweet Dreams", "durationMs": 216000, "artists": [{"name": "Eurythmics"}]},
                ]
            }

        resolver = NuclearResolver(transport=transport)

        self.assertEqual(resolver.resolve_track_query("sweet dreams"), "Eurythmics - Sweet Dreams official audio")

    def test_resolve_album_returns_track_queries_in_album_order(self):
        def transport(method, params):
            if method == "Metadata.search":
                return {
                    "albums": [
                        {
                            "title": "Discovery",
                            "source": {"id": "1550545", "provider": "monochrome"},
                        }
                    ]
                }
            if method == "Metadata.fetchAlbumDetails":
                self.assertEqual(params["albumId"], "1550545")
                self.assertEqual(params["providerId"], "monochrome")
                return {
                    "tracks": [
                        {"title": "One More Time", "durationMs": 320000, "artists": [{"name": "Daft Punk"}]},
                        {"title": "Aerodynamic", "durationMs": 213000, "artists": [{"name": "Daft Punk"}]},
                    ]
                }
            raise AssertionError(method)

        resolver = NuclearResolver(transport=transport)

        self.assertEqual(
            resolver.resolve_album_queries("Daft Punk Discovery"),
            [
                "Daft Punk - One More Time official audio",
                "Daft Punk - Aerodynamic official audio",
            ],
        )


if __name__ == "__main__":
    unittest.main()
