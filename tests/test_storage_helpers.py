import sqlite3
import tempfile
import unittest
from pathlib import Path

from metacritic_scraper_py.storage import SQLiteStorage


class StorageHelpersTestCase(unittest.TestCase):
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

    def test_schema_migration_adds_cover_url_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE games (
                        slug TEXT PRIMARY KEY,
                        game_id INTEGER,
                        title TEXT,
                        platform TEXT,
                        release_date TEXT,
                        premiere_year INTEGER,
                        rating TEXT,
                        critic_score REAL,
                        critic_review_count INTEGER,
                        user_score REAL,
                        user_review_count INTEGER,
                        product_json TEXT NOT NULL,
                        critic_summary_json TEXT,
                        user_summary_json TEXT,
                        scraped_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url="https://www.metacritic.com/a/img/catalog/provider/7/2/demo.jpg",
                )
                row = storage.conn.execute("SELECT cover_url FROM games WHERE slug = ?", ("demo-game",)).fetchone()
                self.assertEqual(
                    row[0],
                    "https://www.metacritic.com/a/img/catalog/provider/7/2/demo.jpg",
                )
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
