import tempfile
import unittest
from pathlib import Path

from voice.queue_origin_ledger import QueueOriginLedger


class QueueOriginLedgerTests(unittest.TestCase):
    def test_origins_persist_and_are_consumed_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "origins.json"
            ledger = QueueOriginLedger(path)
            ledger.add(
                42,
                track_key="track:one",
                source="playlist",
                label="Road Trip",
            )

            reopened = QueueOriginLedger(path)
            self.assertEqual(
                reopened.entries(42)[0]["label"],
                "Road Trip",
            )
            self.assertEqual(
                reopened.consume(42, "track:one")["source"],
                "playlist",
            )
            self.assertEqual(reopened.entries(42), [])


if __name__ == "__main__":
    unittest.main()
