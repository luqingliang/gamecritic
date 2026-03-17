import sqlite3
import tempfile
import unittest
from pathlib import Path

from gamecritic.slug_search import build_slug_search_candidate
from gamecritic.storage import SQLiteStorage, load_slug_search_candidates_from_db


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

    def test_clear_all_tables_deletes_rows_and_preserves_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
                storage.upsert_critic_reviews(
                    "demo-game",
                    [
                        {
                            "publicationSlug": "demo-pub",
                            "date": "2026-03-11",
                            "score": 8,
                            "url": "https://example.com/review",
                            "quote": "great game",
                            "author": "reviewer",
                            "publicationName": "Demo Pub",
                        }
                    ],
                )
                storage.upsert_user_reviews(
                    "demo-game",
                    [
                        {
                            "id": "user-1",
                            "author": "player",
                            "date": "2026-03-11",
                            "score": 9,
                            "quote": "loved it",
                            "spoiler": False,
                        }
                    ],
                )
                storage.upsert_indexed_slugs(
                    [("demo-game", "https://example.com/game/demo-game", "https://example.com/games.xml")]
                )
                storage.set_state("checkpoint", "2026-03-11T00:00:00+00:00")

                counts = storage.clear_all_tables()

                self.assertEqual(
                    counts,
                    {
                        "critic_reviews": 1,
                        "user_reviews": 1,
                        "games": 1,
                        "sync_state": 1,
                    },
                )
                for table_name in ("critic_reviews", "user_reviews", "games", "sync_state"):
                    self.assertEqual(storage.count_rows(table_name), 0)

                storage.set_state("checkpoint", "2026-03-12T00:00:00+00:00")
                self.assertEqual(storage.get_state("checkpoint"), "2026-03-12T00:00:00+00:00")
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

    def test_schema_migration_backfills_slug_search_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE games (
                        slug TEXT PRIMARY KEY,
                        game_url TEXT,
                        sitemap_url TEXT,
                        discovered_at TEXT,
                        last_seen_at TEXT,
                        is_crawled INTEGER NOT NULL DEFAULT 0,
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
                        cover_url TEXT,
                        product_json TEXT NOT NULL,
                        critic_summary_json TEXT,
                        user_summary_json TEXT,
                        scraped_at TEXT NOT NULL
                    );
                    INSERT INTO games (
                        slug, game_url, sitemap_url, discovered_at, last_seen_at, is_crawled, title, product_json, scraped_at
                    ) VALUES (
                        'grand-theft-auto-v',
                        'https://example.com/game/grand-theft-auto-v',
                        'https://example.com/games.xml',
                        '2026-03-17T00:00:00+00:00',
                        '2026-03-17T00:00:00+00:00',
                        1,
                        'Grand Theft Auto V',
                        '{}',
                        '2026-03-17T00:00:00+00:00'
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

            storage = SQLiteStorage(db_path)
            try:
                row = storage.conn.execute(
                    """
                    SELECT slug_search_text, title_search_text, slug_acronym, title_acronym
                    FROM games
                    WHERE slug = ?
                    """,
                    ("grand-theft-auto-v",),
                ).fetchone()
                self.assertEqual(
                    row,
                    ("grand theft auto v", "grand theft auto v", "gtav", "gtav"),
                )
            finally:
                storage.close()

    def test_list_slug_search_candidates_prefers_games_title_and_keeps_slug_only_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="elden-ring",
                    product_payload={"data": {"item": {"id": 1, "title": "Elden Ring", "platform": "PC"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
                storage.upsert_indexed_slugs(
                    [
                        (
                            "elden-ring",
                            "https://example.com/game/elden-ring",
                            "https://example.com/games-a.xml",
                        ),
                        (
                            "balatro",
                            "https://example.com/game/balatro",
                            "https://example.com/games-b.xml",
                        ),
                    ]
                )

                self.assertEqual(
                    storage.list_slug_search_candidates(),
                    [
                        build_slug_search_candidate(
                            slug="balatro",
                            title=None,
                            slug_search_text="balatro",
                            title_search_text="",
                            slug_acronym="b",
                            title_acronym="",
                        ),
                        build_slug_search_candidate(
                            slug="elden-ring",
                            title="Elden Ring",
                            slug_search_text="elden ring",
                            title_search_text="elden ring",
                            slug_acronym="er",
                            title_acronym="er",
                        ),
                    ],
                )

                row = storage.conn.execute(
                    """
                    SELECT slug_search_text, title_search_text, slug_acronym, title_acronym
                    FROM games
                    WHERE slug = ?
                    """,
                    ("elden-ring",),
                ).fetchone()
                self.assertEqual(row, ("elden ring", "elden ring", "er", "er"))
            finally:
                storage.close()

    def test_list_slug_search_candidates_query_limits_shortlist_to_top_100(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_indexed_slugs(
                    [
                        (
                            f"demo-game-{index:03d}",
                            f"https://example.com/game/demo-game-{index:03d}",
                            "https://example.com/games.xml",
                        )
                        for index in range(120)
                    ]
                )

                matches = storage.list_slug_search_candidates(query="demo game", limit=100)

                self.assertEqual(len(matches), 100)
                self.assertTrue(all(match.slug.startswith("demo-game-") for match in matches))
            finally:
                storage.close()

    def test_list_slug_search_candidates_query_matches_acronym_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_indexed_slugs(
                    [
                        (
                            "grand-theft-auto-v",
                            "https://example.com/game/grand-theft-auto-v",
                            "https://example.com/games.xml",
                        ),
                        (
                            "grand-theft-auto-san-andreas",
                            "https://example.com/game/grand-theft-auto-san-andreas",
                            "https://example.com/games.xml",
                        ),
                        (
                            "elden-ring",
                            "https://example.com/game/elden-ring",
                            "https://example.com/games.xml",
                        ),
                    ]
                )

                matches = storage.list_slug_search_candidates(query="GTA", limit=100)

                self.assertEqual(
                    [match.slug for match in matches[:2]],
                    ["grand-theft-auto-v", "grand-theft-auto-san-andreas"],
                )
                self.assertNotIn("elden-ring", [match.slug for match in matches])
            finally:
                storage.close()

    def test_load_slug_search_candidates_from_db_does_not_create_missing_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing.db"
            self.assertFalse(db_path.exists())

            self.assertEqual(load_slug_search_candidates_from_db(db_path), [])
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
