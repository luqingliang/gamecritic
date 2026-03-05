import tempfile
import unittest
from pathlib import Path

from metacritic_scraper_py.scraper import MetacriticScraper
from metacritic_scraper_py.storage import SQLiteStorage


class IncrementalHelpersTestCase(unittest.TestCase):
    def test_parse_iso_date(self) -> None:
        self.assertEqual(str(MetacriticScraper._parse_iso_date("2026-03-05")), "2026-03-05")
        self.assertIsNone(MetacriticScraper._parse_iso_date("2026/03/05"))
        self.assertIsNone(MetacriticScraper._parse_iso_date(None))

    def test_sync_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                self.assertIsNone(storage.get_state("k1"))
                storage.set_state("k1", "2026-03-05")
                self.assertEqual(storage.get_state("k1"), "2026-03-05")
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
