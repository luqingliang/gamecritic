import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from gamecritic.client import MetacriticClientError
from gamecritic.cli import _build_serve_namespace, _interactive_defaults, build_parser, main, run_serve
from gamecritic.storage import SQLiteStorage
from gamecritic.web_service import GamecriticWebService, WebServiceConfig, WebServiceError


class _NeverUsedClient:
    def __enter__(self) -> "_NeverUsedClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __getattr__(self, name: str):
        raise AssertionError(f"client method should not be called: {name}")


class _FakeWebServiceClient:
    def __init__(
        self,
        *,
        products: dict[str, dict] | None = None,
        critic_summaries: dict[str, dict] | None = None,
        user_summaries: dict[str, dict] | None = None,
        critic_reviews: dict[str, list[dict]] | None = None,
        user_reviews: dict[str, list[dict]] | None = None,
        critic_review_errors: dict[str, Exception] | None = None,
        user_review_errors: dict[str, Exception] | None = None,
    ) -> None:
        self._products = dict(products or {})
        self._critic_summaries = dict(critic_summaries or {})
        self._user_summaries = dict(user_summaries or {})
        self._critic_reviews = dict(critic_reviews or {})
        self._user_reviews = dict(user_reviews or {})
        self._critic_review_errors = dict(critic_review_errors or {})
        self._user_review_errors = dict(user_review_errors or {})
        self.review_calls: list[tuple[str, str]] = []

    def __enter__(self) -> "_FakeWebServiceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def fetch_product(self, slug: str) -> dict:
        return self._products[slug]

    def resolve_cover_url(self, *, product_payload: dict) -> str | None:
        del product_payload
        return "https://www.metacritic.com/a/img/catalog/provider/1/1/demo.jpg"

    def fetch_score_summary(self, slug: str, review_type: str) -> dict | None:
        if review_type == "critic":
            return self._critic_summaries.get(slug)
        return self._user_summaries.get(slug)

    def iter_reviews(
        self,
        *,
        slug: str,
        review_type: str,
        page_size: int = 50,
        max_pages: int | None = None,
    ):
        del page_size, max_pages
        self.review_calls.append((slug, review_type))
        if review_type == "critic":
            error = self._critic_review_errors.get(slug)
            if error is not None:
                raise error
            yield from self._critic_reviews.get(slug, [])
            return
        error = self._user_review_errors.get(slug)
        if error is not None:
            raise error
        yield from self._user_reviews.get(slug, [])


class WebServiceCliTestCase(unittest.TestCase):
    def test_parser_accepts_serve_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve"])
        self.assertEqual(args.command, "serve")
        self.assertIn("serve", parser.format_help())

    def test_build_serve_namespace_uses_shared_settings(self) -> None:
        settings = _interactive_defaults()
        settings["db"] = "data/custom.db"
        settings["server_host"] = "0.0.0.0"
        settings["server_port"] = 9100
        settings["review_page_size"] = 25

        args = _build_serve_namespace(settings)

        self.assertEqual(args.command, "serve")
        self.assertEqual(args.db, "data/custom.db")
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9100)
        self.assertEqual(args.review_page_size, 25)

    def test_main_dispatches_serve_command(self) -> None:
        settings = _interactive_defaults()
        settings["server_host"] = "0.0.0.0"
        settings["server_port"] = 9200

        with patch("gamecritic.cli._load_shared_settings", return_value=settings), patch(
            "gamecritic.cli.run_serve",
            return_value=0,
        ) as run_serve_mock:
            exit_code = main(["serve"])

        self.assertEqual(exit_code, 0)
        dispatched_args = run_serve_mock.call_args.args[0]
        self.assertEqual(dispatched_args.command, "serve")
        self.assertEqual(dispatched_args.host, "0.0.0.0")
        self.assertEqual(dispatched_args.port, 9200)

    def test_run_serve_returns_130_when_stop_event_is_requested(self) -> None:
        args = _build_serve_namespace(_interactive_defaults(), stop_event=threading.Event())
        args.stop_event.set()

        class _FakeService:
            def __init__(self) -> None:
                self.server_address = ("127.0.0.1", 8000)
                self.shutdown_called = threading.Event()
                self.closed = False

            def serve_forever(self) -> None:
                self.shutdown_called.wait(1.0)

            def shutdown(self) -> None:
                self.shutdown_called.set()

            def close(self) -> None:
                self.closed = True

        fake_service = _FakeService()

        with patch("gamecritic.cli.GamecriticWebService", return_value=fake_service):
            exit_code = run_serve(args)

        self.assertEqual(exit_code, 130)
        self.assertTrue(fake_service.shutdown_called.is_set())
        self.assertTrue(fake_service.closed)

    def test_web_service_init_skips_storage_when_bind_fails(self) -> None:
        config = WebServiceConfig(
            host="127.0.0.1",
            port=8000,
            include_critic_reviews=False,
            include_user_reviews=False,
            review_page_size=50,
            max_review_pages=1,
        )

        with patch("gamecritic.web_service._GamecriticHTTPServer", side_effect=OSError("address in use")), patch(
            "gamecritic.web_service.SQLiteStorage"
        ) as storage_mock:
            with self.assertRaises(OSError):
                GamecriticWebService(
                    db_path="data/test.db",
                    config=config,
                    client_factory=lambda: _NeverUsedClient(),
                )

        storage_mock.assert_not_called()


class WebServiceApiTestCase(unittest.TestCase):
    def _build_service(
        self,
        *,
        db_path: Path,
        client_factory,
        include_critic_reviews: bool = False,
        include_user_reviews: bool = False,
        stop_event: threading.Event | None = None,
    ) -> GamecriticWebService:
        return GamecriticWebService(
            db_path=str(db_path),
            config=WebServiceConfig(
                host="127.0.0.1",
                port=0,
                include_critic_reviews=include_critic_reviews,
                include_user_reviews=include_user_reviews,
                review_page_size=50,
                max_review_pages=1,
            ),
            client_factory=client_factory,
            stop_event=stop_event,
            bind_server=False,
        )

    def _dispatch(self, service: GamecriticWebService, path: str) -> tuple[int, dict]:
        try:
            return service.dispatch_path(path)
        except WebServiceError as exc:
            return exc.status_code, {"ok": False, "error": exc.message}

    def test_game_endpoint_returns_cached_game_without_crawling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                    critic_summary_payload={"data": {"item": {"score": 91, "reviewCount": 12}}},
                    user_summary_payload={"data": {"item": {"score": 8.8, "reviewCount": 99}}},
                    cover_url="https://www.metacritic.com/a/img/catalog/provider/1/1/demo.jpg",
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/game?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["slug"], "demo-game")
        self.assertEqual(payload["data"]["title"], "Demo Game")
        self.assertFalse(payload["data"]["auto_crawled"])

    def test_game_endpoint_refreshes_stale_cached_game_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Old Demo Game", "platform": "PC"}}},
                    critic_summary_payload={"data": {"item": {"score": 70, "reviewCount": 5}}},
                    user_summary_payload={"data": {"item": {"score": 7.0, "reviewCount": 12}}},
                    cover_url=None,
                )
                storage.conn.execute(
                    "UPDATE games SET scraped_at = ? WHERE slug = ?",
                    ("2026-01-01T00:00:00+00:00", "demo-game"),
                )
                storage.conn.commit()
            finally:
                storage.close()

            def _client_factory() -> _FakeWebServiceClient:
                return _FakeWebServiceClient(
                    products={
                        "demo-game": {
                            "data": {
                                "item": {
                                    "id": 7,
                                    "title": "Demo Game Refreshed",
                                    "platform": "PC",
                                    "releaseDate": "2026-03-16",
                                    "premiereYear": 2026,
                                    "rating": "T",
                                }
                            }
                        }
                    },
                    critic_summaries={"demo-game": {"data": {"item": {"score": 90, "reviewCount": 10}}}},
                    user_summaries={"demo-game": {"data": {"item": {"score": 8.7, "reviewCount": 20}}}},
                )

            service = self._build_service(
                db_path=db_path,
                client_factory=_client_factory,
            )
            try:
                status, payload = self._dispatch(service, "/api/game?slug=demo-game")
            finally:
                service.close()

            storage = SQLiteStorage(db_path)
            try:
                game = storage.get_game("demo-game")
            finally:
                storage.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["auto_crawled"])
        self.assertEqual(payload["data"]["title"], "Demo Game Refreshed")
        self.assertIsNotNone(game)
        self.assertEqual(game["title"], "Demo Game Refreshed")

    def test_game_endpoint_crawls_and_persists_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            def _client_factory() -> _FakeWebServiceClient:
                return _FakeWebServiceClient(
                    products={
                        "demo-game": {
                            "data": {
                                "item": {
                                    "id": 7,
                                    "title": "Demo Game",
                                    "platform": "PC",
                                    "releaseDate": "2026-03-16",
                                    "premiereYear": 2026,
                                    "rating": "T",
                                }
                            }
                        }
                    },
                    critic_summaries={"demo-game": {"data": {"item": {"score": 90, "reviewCount": 10}}}},
                    user_summaries={"demo-game": {"data": {"item": {"score": 8.7, "reviewCount": 20}}}},
                )

            service = self._build_service(
                db_path=db_path,
                client_factory=_client_factory,
            )
            try:
                status, payload = self._dispatch(service, "/api/game?slug=demo-game")
            finally:
                service.close()

            storage = SQLiteStorage(db_path)
            try:
                game = storage.get_game("demo-game")
            finally:
                storage.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["auto_crawled"])
        self.assertEqual(payload["data"]["title"], "Demo Game")
        self.assertIsNotNone(game)
        self.assertEqual(game["title"], "Demo Game")

    def test_game_endpoint_does_not_fetch_reviews_when_crawling_missing_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            client = _FakeWebServiceClient(
                products={
                    "demo-game": {
                        "data": {
                            "item": {
                                "id": 7,
                                "title": "Demo Game",
                                "platform": "PC",
                            }
                        }
                    }
                },
                critic_summaries={"demo-game": {"data": {"item": {"score": 90, "reviewCount": 10}}}},
                user_summaries={"demo-game": {"data": {"item": {"score": 8.7, "reviewCount": 20}}}},
                critic_reviews={"demo-game": [{"publicationName": "Should Not Load"}]},
                user_reviews={"demo-game": [{"author": "Should Not Load"}]},
            )
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: client,
                include_critic_reviews=True,
                include_user_reviews=True,
            )
            try:
                status, payload = self._dispatch(service, "/api/game?slug=demo-game")
            finally:
                service.close()

            storage = SQLiteStorage(db_path)
            try:
                critic_reviews = storage.list_critic_review_payloads("demo-game")
                user_reviews = storage.list_user_review_payloads("demo-game")
            finally:
                storage.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(client.review_calls, [])
        self.assertEqual(critic_reviews, [])
        self.assertEqual(user_reviews, [])

    def test_search_endpoint_returns_selected_best_match(self) -> None:
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
                            "metaphor-refantazio",
                            "https://www.metacritic.com/game/metaphor-refantazio/",
                            "https://www.metacritic.com/games.xml",
                        )
                    ]
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/search?q=Elden%20Ring")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["status"], "matched")
        self.assertEqual(payload["data"]["selected"]["slug"], "elden-ring")
        self.assertEqual(payload["data"]["matches"][0]["slug"], "elden-ring")

    def test_search_endpoint_returns_ambiguous_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="resident-evil-4",
                    product_payload={"data": {"item": {"id": 1, "title": "Resident Evil 4", "platform": "PC"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
                storage.upsert_game(
                    slug="resident-evil-village",
                    product_payload={"data": {"item": {"id": 2, "title": "Resident Evil Village", "platform": "PC"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/search?q=Resident%20Evil")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["status"], "ambiguous")
        self.assertIsNone(payload["data"]["selected"])
        self.assertGreaterEqual(payload["data"]["total_matches"], 2)
        self.assertGreaterEqual(len(payload["data"]["matches"]), 2)

    def test_search_endpoint_returns_all_matches_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                for index in range(6):
                    storage.upsert_game(
                        slug=f"elden-ring-variant-{index}",
                        product_payload={
                            "data": {"item": {"id": index + 1, "title": "Elden Ring", "platform": "PC"}}
                        },
                        critic_summary_payload=None,
                        user_summary_payload=None,
                        cover_url=None,
                    )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/search?q=Elden%20Ring")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["status"], "ambiguous")
        self.assertEqual(payload["data"]["total_matches"], 6)
        self.assertEqual(len(payload["data"]["matches"]), 6)

    def test_search_endpoint_requires_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/search")
            finally:
                service.close()

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("q", payload["error"])

    def test_search_endpoint_filters_out_matches_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="resident-evil-village",
                    product_payload={
                        "data": {"item": {"id": 1, "title": "Resident Evil Village", "platform": "PC"}}
                    },
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/search?q=RE%20Village%20DLC")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["status"], "no_match")
        self.assertEqual(payload["data"]["matches"], [])
        self.assertIsNone(payload["data"]["selected"])

    def test_reviews_endpoint_backfills_reviews_and_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            def _client_factory() -> _FakeWebServiceClient:
                return _FakeWebServiceClient(
                    products={
                        "demo-game": {
                            "data": {
                                "item": {
                                    "id": 9,
                                    "title": "Demo Game",
                                    "platform": "PC",
                                }
                            }
                        }
                    },
                    critic_reviews={
                        "demo-game": [
                            {
                                "publicationSlug": "demo-pub",
                                "publicationName": "Demo Pub",
                                "date": "2026-03-16",
                                "score": 80,
                                "url": "https://example.com/critic-review",
                                "quote": "Great game.",
                                "author": "Critic A",
                            }
                        ]
                    },
                    user_reviews={
                        "demo-game": [
                            {
                                "id": "user-1",
                                "author": "User A",
                                "date": "2026-03-16",
                                "score": 9,
                                "quote": "Loved it.",
                                "spoiler": False,
                            }
                        ]
                    },
                )

            service = self._build_service(
                db_path=db_path,
                client_factory=_client_factory,
            )
            try:
                status, payload = self._dispatch(service, "/api/reviews?slug=demo-game")
            finally:
                service.close()

            storage = SQLiteStorage(db_path)
            try:
                critic_reviews = storage.list_critic_review_payloads("demo-game")
                user_reviews = storage.list_user_review_payloads("demo-game")
            finally:
                storage.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["slug"], "demo-game")
        self.assertFalse(payload["data"]["game_auto_crawled"])
        self.assertEqual(payload["data"]["counts"]["critic_reviews"], 1)
        self.assertEqual(payload["data"]["counts"]["user_reviews"], 1)
        self.assertEqual(len(critic_reviews), 1)
        self.assertEqual(len(user_reviews), 1)

    def test_reviews_endpoint_returns_502_when_review_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                    critic_summary_payload=None,
                    user_summary_payload=None,
                    cover_url=None,
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _FakeWebServiceClient(
                    critic_review_errors={
                        "demo-game": MetacriticClientError("status code 404 for latest critic reviews")
                    }
                ),
            )
            try:
                status, payload = self._dispatch(service, "/api/reviews?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 502)
        self.assertFalse(payload["ok"])
        self.assertIn("critic", payload["error"])

    def test_reviews_endpoint_returns_cached_reviews_without_crawling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                    critic_summary_payload={"data": {"item": {"score": 90, "reviewCount": 1}}},
                    user_summary_payload={"data": {"item": {"score": 8.7, "reviewCount": 1}}},
                    cover_url=None,
                )
                storage.upsert_critic_reviews(
                    "demo-game",
                    [
                        {
                            "publicationSlug": "demo-pub",
                            "publicationName": "Demo Pub",
                            "date": "2026-03-16",
                            "score": 80,
                            "url": "https://example.com/critic-review",
                            "quote": "Great game.",
                            "author": "Critic A",
                        }
                    ],
                )
                storage.upsert_user_reviews(
                    "demo-game",
                    [
                        {
                            "id": "user-1",
                            "author": "User A",
                            "date": "2026-03-16",
                            "score": 9,
                            "quote": "Loved it.",
                            "spoiler": False,
                        }
                    ],
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/reviews?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["data"]["game_auto_crawled"])
        self.assertEqual(payload["data"]["counts"]["critic_reviews"], 1)
        self.assertEqual(payload["data"]["counts"]["user_reviews"], 1)

    def test_reviews_endpoint_refreshes_stale_cached_reviews_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                    critic_summary_payload={"data": {"item": {"score": 90, "reviewCount": 1}}},
                    user_summary_payload={"data": {"item": {"score": 8.7, "reviewCount": 1}}},
                    cover_url=None,
                )
                storage.upsert_critic_reviews(
                    "demo-game",
                    [
                        {
                            "publicationSlug": "demo-pub",
                            "publicationName": "Old Demo Pub",
                            "date": "2026-01-10",
                            "score": 70,
                            "url": "https://example.com/old-critic-review",
                            "quote": "Old quote.",
                            "author": "Critic A",
                        }
                    ],
                )
                storage.upsert_user_reviews(
                    "demo-game",
                    [
                        {
                            "id": "user-1",
                            "author": "User A",
                            "date": "2026-01-10",
                            "score": 7,
                            "quote": "Old user quote.",
                            "spoiler": False,
                        }
                    ],
                )
                storage.conn.execute(
                    "UPDATE critic_reviews SET scraped_at = ? WHERE slug = ?",
                    ("2026-01-10T00:00:00+00:00", "demo-game"),
                )
                storage.conn.execute(
                    "UPDATE user_reviews SET scraped_at = ? WHERE slug = ?",
                    ("2026-01-10T00:00:00+00:00", "demo-game"),
                )
                storage.conn.commit()
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _FakeWebServiceClient(
                    critic_reviews={
                        "demo-game": [
                            {
                                "publicationSlug": "demo-pub",
                                "publicationName": "New Demo Pub",
                                "date": "2026-03-16",
                                "score": 85,
                                "url": "https://example.com/new-critic-review",
                                "quote": "New quote.",
                                "author": "Critic A",
                            }
                        ]
                    },
                    user_reviews={
                        "demo-game": [
                            {
                                "id": "user-1",
                                "author": "User A",
                                "date": "2026-03-16",
                                "score": 9,
                                "quote": "New user quote.",
                                "spoiler": False,
                            }
                        ]
                    },
                ),
            )
            try:
                status, payload = self._dispatch(service, "/api/reviews?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["critic_reviews"][0]["publicationName"], "New Demo Pub")
        self.assertEqual(payload["data"]["user_reviews"][0]["quote"], "New user quote.")

    def test_reviews_endpoint_returns_empty_cached_response_when_game_summary_counts_are_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = SQLiteStorage(db_path)
            try:
                storage.upsert_game(
                    slug="demo-game",
                    product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                    critic_summary_payload={"data": {"item": {"score": None, "reviewCount": 0}}},
                    user_summary_payload={"data": {"item": {"score": None, "reviewCount": 0}}},
                    cover_url=None,
                )
            finally:
                storage.close()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/reviews?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["counts"]["critic_reviews"], 0)
        self.assertEqual(payload["data"]["counts"]["user_reviews"], 0)
        self.assertEqual(payload["data"]["critic_reviews"], [])
        self.assertEqual(payload["data"]["user_reviews"], [])

    def test_service_shutdown_sets_stop_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            stop_event = threading.Event()
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
                stop_event=stop_event,
            )
            try:
                service.shutdown()
            finally:
                service.close()

        self.assertTrue(stop_event.is_set())

    def test_game_endpoint_passes_service_stop_event_to_scraper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            stop_event = threading.Event()
            captured: dict[str, object] = {}

            class _FakeScraper:
                def __init__(self, client, storage, *, stop_event=None) -> None:
                    del client
                    captured["stop_event"] = stop_event
                    self._storage = storage

                def crawl_slug(self, slug: str, **kwargs):
                    del kwargs
                    self._storage.upsert_game(
                        slug=slug,
                        product_payload={"data": {"item": {"id": 1, "title": "Demo Game", "platform": "PC"}}},
                        critic_summary_payload=None,
                        user_summary_payload=None,
                        cover_url=None,
                    )
                    return type("Result", (), {"stopped": False})()

            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
                stop_event=stop_event,
            )
            try:
                with patch("gamecritic.web_service.MetacriticScraper", _FakeScraper):
                    status, payload = self._dispatch(service, "/api/game?slug=demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIs(captured.get("stop_event"), stop_event)

    def test_game_endpoint_requires_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, payload = self._dispatch(service, "/api/game")
            finally:
                service.close()

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("slug", payload["error"])

    def test_frontend_root_route_returns_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, content_type, body = service.dispatch_frontend_path("/")
            finally:
                service.close()

        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn("<title>Gamecritic</title>", text)
        self.assertIn('id="slug-form"', text)
        self.assertIn('id="lang-switch"', text)
        self.assertIn('id="status-card"', text)
        self.assertIn('/static/app.js', text)

    def test_frontend_game_route_returns_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, content_type, body = service.dispatch_frontend_path("/game/demo-game")
            finally:
                service.close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('id="reviews-title"', body.decode("utf-8"))

    def test_frontend_static_asset_returns_javascript(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            service = self._build_service(
                db_path=db_path,
                client_factory=lambda: _NeverUsedClient(),
            )
            try:
                status, content_type, body = service.dispatch_frontend_path("/static/app.js")
            finally:
                service.close()

        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        self.assertIn("loadSlug", text)
        self.assertIn("RECENT_GAMES_KEY", text)
        self.assertIn("LANGUAGE_KEY", text)


if __name__ == "__main__":
    unittest.main()
