import threading
import unittest
from unittest.mock import patch

from gamecritic.bot_callbacks import (
    build_critic_reviews_open_callback,
    build_critic_reviews_page_callback,
    build_game_detail_callback,
    parse_callback_data,
)
from gamecritic.bot_handlers import TelegramBotHandler
from gamecritic.cli import (
    _build_serve_namespace,
    _build_telegram_bot_namespace,
    _interactive_defaults,
    _load_bot_settings,
    _telegram_bot_defaults,
    build_parser,
    run_telegram_bot,
    run_serve,
)
from gamecritic.telegram_bot import GamecriticTelegramBot, TelegramApiError, TelegramBotConfig, TelegramBotTransport, _poll_retry_delay


class _FakeBackendClient:
    def __init__(
        self,
        *,
        search_payload: dict | None = None,
        games: dict[str, dict] | None = None,
        reviews: dict[str, dict] | None = None,
    ) -> None:
        self.search_payload = dict(search_payload or {})
        self.games = dict(games or {})
        self.reviews = dict(reviews or {})
        self.search_calls: list[str] = []
        self.game_calls: list[str] = []
        self.review_calls: list[str] = []

    def search_games(self, query: str) -> dict:
        self.search_calls.append(query)
        return dict(self.search_payload)

    def get_game(self, slug: str) -> dict:
        self.game_calls.append(slug)
        return dict(self.games[slug])

    def get_reviews(self, slug: str) -> dict:
        self.review_calls.append(slug)
        return dict(self.reviews[slug])

    def close(self) -> None:
        return None


class _FakeTransport:
    def __init__(self, *, photo_error: Exception | None = None) -> None:
        self.photo_error = photo_error
        self.sent_messages: list[dict] = []
        self.sent_photos: list[dict] = []
        self.edited_messages: list[dict] = []
        self.answered_callback_queries: list[str] = []

    def send_message(self, *, chat_id: int, text: str, buttons=()):
        payload = {"chat_id": chat_id, "text": text, "buttons": buttons}
        self.sent_messages.append(payload)
        return payload

    def send_photo(self, *, chat_id: int, photo_url: str, caption: str, buttons=()):
        if self.photo_error is not None:
            raise self.photo_error
        payload = {"chat_id": chat_id, "photo_url": photo_url, "caption": caption, "buttons": buttons}
        self.sent_photos.append(payload)
        return payload

    def edit_message_text(self, *, chat_id: int, message_id: int, text: str, buttons=()):
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}
        self.edited_messages.append(payload)
        return payload

    def answer_callback_query(self, *, callback_query_id: str):
        self.answered_callback_queries.append(callback_query_id)
        return {"ok": True}

    def close(self) -> None:
        return None


class _RecordingStopEvent:
    def __init__(self) -> None:
        self.wait_calls: list[float] = []
        self._is_set = False

    def is_set(self) -> bool:
        return self._is_set

    def set(self) -> None:
        self._is_set = True

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls.append(0.0 if timeout is None else float(timeout))
        self._is_set = True
        return True


class TelegramBotCliTestCase(unittest.TestCase):
    def test_parser_does_not_expose_standalone_telegram_bot_command(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["telegram-bot"])
        self.assertNotIn("telegram-bot", parser.format_help())

    def test_build_telegram_bot_namespace_uses_bot_settings(self) -> None:
        settings = _telegram_bot_defaults()
        settings["backend_base_url"] = "http://127.0.0.1:9000"
        settings["bot_token"] = "bot-token"
        settings["critic_reviews_per_page"] = 7

        args = _build_telegram_bot_namespace(settings)

        self.assertEqual(args.command, "telegram-bot")
        self.assertEqual(args.backend_base_url, "http://127.0.0.1:9000")
        self.assertEqual(args.bot_token, "bot-token")
        self.assertEqual(args.critic_reviews_per_page, 7)

    def test_load_bot_settings_returns_defaults_when_file_missing(self) -> None:
        with patch("gamecritic.cli.BOT_SETTINGS_PATH", "config/missing-bot-settings.json"):
            settings = _load_bot_settings()
        self.assertEqual(settings["backend_base_url"], "http://127.0.0.1:8000")
        self.assertEqual(settings["critic_reviews_per_page"], 5)

    def test_run_telegram_bot_requires_token_in_settings_file(self) -> None:
        args = _build_telegram_bot_namespace(_telegram_bot_defaults())
        with self.assertRaises(SystemExit) as exc:
            run_telegram_bot(args)
        self.assertIn("bot_token must be configured", str(exc.exception))

    def test_run_serve_warns_and_continues_when_bot_token_missing(self) -> None:
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
        with patch("gamecritic.cli.GamecriticWebService", return_value=fake_service), patch(
            "gamecritic.cli._load_bot_settings",
            return_value=_telegram_bot_defaults(),
        ), self.assertLogs(level="WARNING") as captured_logs:
            exit_code = run_serve(args)

        self.assertEqual(exit_code, 130)
        self.assertTrue(fake_service.closed)
        self.assertTrue(
            any("telegram bot disabled: bot_token must be configured in config/bot_settings.json" in line for line in captured_logs.output)
        )

    def test_run_serve_starts_telegram_bot_when_bot_settings_are_valid(self) -> None:
        args = _build_serve_namespace(_interactive_defaults(), stop_event=threading.Event())
        args.stop_event.set()
        bot_settings = _telegram_bot_defaults()
        bot_settings["bot_token"] = "demo-bot-token"

        class _FakeService:
            def __init__(self) -> None:
                self.server_address = ("0.0.0.0", 9100)
                self.shutdown_called = threading.Event()
                self.closed = False

            def serve_forever(self) -> None:
                self.shutdown_called.wait(1.0)

            def shutdown(self) -> None:
                self.shutdown_called.set()

            def close(self) -> None:
                self.closed = True

        class _FakeBot:
            def __init__(self) -> None:
                self.closed = False
                self.served = threading.Event()
                self.close_called = threading.Event()

            def serve_forever(self) -> None:
                self.served.set()
                self.close_called.wait(1.0)

            def close(self) -> None:
                self.closed = True
                self.close_called.set()

        fake_service = _FakeService()
        fake_bot = _FakeBot()
        with patch("gamecritic.cli.GamecriticWebService", return_value=fake_service), patch(
            "gamecritic.cli._load_bot_settings",
            return_value=bot_settings,
        ), patch("gamecritic.cli.GamecriticTelegramBot", return_value=fake_bot) as bot_mock:
            exit_code = run_serve(args)

        self.assertEqual(exit_code, 130)
        self.assertTrue(fake_service.closed)
        self.assertTrue(fake_bot.served.is_set())
        self.assertTrue(fake_bot.closed)
        config = bot_mock.call_args.kwargs["config"]
        self.assertEqual(config.bot_token, "demo-bot-token")
        self.assertEqual(config.backend_base_url, "http://127.0.0.1:9100")


class TelegramBotTransportTestCase(unittest.TestCase):
    def test_transport_exposes_retry_after_from_telegram_response(self) -> None:
        class _FakeResponse:
            status_code = 429

            def json(self) -> dict:
                return {
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry after 5",
                    "parameters": {"retry_after": 5},
                }

        class _FakeClient:
            def post(self, path: str, json: dict) -> _FakeResponse:
                self.path = path
                self.payload = dict(json)
                return _FakeResponse()

            def close(self) -> None:
                return None

        fake_client = _FakeClient()
        with patch("gamecritic.telegram_bot.httpx.Client", return_value=fake_client):
            transport = TelegramBotTransport(
                api_base_url="https://api.telegram.org",
                bot_token="demo-bot-token",
                request_timeout=5.0,
            )

        with self.assertRaises(TelegramApiError) as exc:
            transport.get_updates(offset=10, timeout=30)

        self.assertEqual(exc.exception.status_code, 429)
        self.assertEqual(exc.exception.retry_after, 5.0)
        self.assertEqual(fake_client.path, "/getUpdates")
        self.assertEqual(fake_client.payload, {"timeout": 30, "offset": 10})

    def test_poll_retry_delay_prefers_retry_after(self) -> None:
        delay = _poll_retry_delay(
            TelegramApiError("Too Many Requests: retry after 5", status_code=429, retry_after=5.0),
            failure_streak=3,
        )
        self.assertEqual(delay, 5.0)

    def test_poll_retry_delay_backs_off_for_transient_errors(self) -> None:
        gateway_delay = _poll_retry_delay(TelegramApiError("Bad Gateway", status_code=502), failure_streak=1)
        timeout_delay = _poll_retry_delay(
            TelegramApiError("telegram getUpdates request failed: The read operation timed out"),
            failure_streak=3,
        )

        self.assertEqual(gateway_delay, 2.0)
        self.assertEqual(timeout_delay, 8.0)


class TelegramCallbackTestCase(unittest.TestCase):
    def test_parse_callback_data_handles_all_supported_actions(self) -> None:
        self.assertEqual(parse_callback_data(build_game_detail_callback("elden-ring")).kind, "game")
        self.assertEqual(parse_callback_data(build_critic_reviews_open_callback("elden-ring")).kind, "critic_open")
        action = parse_callback_data(build_critic_reviews_page_callback("elden-ring", 2))
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "critic_page")
        self.assertEqual(action.page, 2)

    def test_long_slug_callbacks_fall_back_to_short_tokens(self) -> None:
        long_slug = "grand-theft-auto-v-" + ("episode-" * 24)

        game_callback = build_game_detail_callback(long_slug)
        critic_open_callback = build_critic_reviews_open_callback(long_slug)
        critic_page_callback = build_critic_reviews_page_callback(long_slug, 3)

        self.assertLessEqual(len(game_callback.encode("utf-8")), 64)
        self.assertLessEqual(len(critic_open_callback.encode("utf-8")), 64)
        self.assertLessEqual(len(critic_page_callback.encode("utf-8")), 64)

        game_action = parse_callback_data(game_callback)
        self.assertIsNotNone(game_action)
        self.assertEqual(game_action.kind, "game")
        self.assertEqual(game_action.slug, long_slug)

        critic_open_action = parse_callback_data(critic_open_callback)
        self.assertIsNotNone(critic_open_action)
        self.assertEqual(critic_open_action.kind, "critic_open")
        self.assertEqual(critic_open_action.slug, long_slug)
        self.assertEqual(critic_open_action.page, 1)

        critic_page_action = parse_callback_data(critic_page_callback)
        self.assertIsNotNone(critic_page_action)
        self.assertEqual(critic_page_action.kind, "critic_page")
        self.assertEqual(critic_page_action.slug, long_slug)
        self.assertEqual(critic_page_action.page, 3)


class TelegramBotHandlerTestCase(unittest.TestCase):
    def test_handle_start_message_sends_welcome_text(self) -> None:
        backend = _FakeBackendClient()
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )

        handler.handle_update({"message": {"chat": {"id": 101}, "text": "/start"}})

        self.assertEqual(len(transport.sent_messages), 1)
        self.assertIn("直接发送游戏名即可查询", transport.sent_messages[0]["text"])

    def test_handle_search_message_sends_result_buttons(self) -> None:
        backend = _FakeBackendClient(
            search_payload={
                "query": "Elden",
                "selected": None,
                "matches": [
                    {"slug": "elden-ring", "title": "Elden Ring"},
                    {"slug": "elden-ring-nightreign", "title": "Elden Ring Nightreign"},
                ],
            }
        )
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )

        handler.handle_update({"message": {"chat": {"id": 101}, "text": "Elden"}})

        self.assertEqual(backend.search_calls, ["Elden"])
        self.assertEqual(len(transport.sent_messages), 1)
        self.assertIn("搜索结果：Elden", transport.sent_messages[0]["text"])
        first_button = transport.sent_messages[0]["buttons"][0][0]
        self.assertEqual(first_button.callback_data, "g:elden-ring")

    def test_handle_search_message_uses_short_callback_for_long_slug(self) -> None:
        long_slug = "grand-theft-auto-v-" + ("episode-" * 24)
        backend = _FakeBackendClient(
            search_payload={
                "query": "Grand Theft Auto",
                "selected": None,
                "matches": [
                    {"slug": long_slug, "title": "Grand Theft Auto V"},
                ],
            }
        )
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )

        handler.handle_update({"message": {"chat": {"id": 101}, "text": "Grand Theft Auto"}})

        self.assertEqual(len(transport.sent_messages), 1)
        first_button = transport.sent_messages[0]["buttons"][0][0]
        self.assertLessEqual(len(first_button.callback_data.encode("utf-8")), 64)
        action = parse_callback_data(first_button.callback_data)
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "game")
        self.assertEqual(action.slug, long_slug)

    def test_handle_search_message_sends_game_detail_photo_when_selected(self) -> None:
        long_slug = "elden-ring-" + ("nightreign-" * 20)
        backend = _FakeBackendClient(
            search_payload={"query": "Elden Ring", "selected": {"slug": long_slug}, "matches": []},
            games={
                long_slug: {
                    "slug": long_slug,
                    "title": "Elden Ring",
                    "platform": "PC",
                    "release_date": "2022-02-25",
                    "critic_score": 96,
                    "user_score": 8.2,
                    "critic_review_count": 90,
                    "cover_url": "https://example.com/elden.jpg",
                }
            },
        )
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )

        handler.handle_update({"message": {"chat": {"id": 101}, "text": "Elden Ring"}})

        self.assertEqual(backend.game_calls, [long_slug])
        self.assertEqual(len(transport.sent_photos), 1)
        self.assertIn("Elden Ring", transport.sent_photos[0]["caption"])
        button = transport.sent_photos[0]["buttons"][0][0]
        self.assertLessEqual(len(button.callback_data.encode("utf-8")), 64)
        action = parse_callback_data(button.callback_data)
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "critic_open")
        self.assertEqual(action.slug, long_slug)

    def test_handle_callback_query_sends_first_critic_review_page(self) -> None:
        backend = _FakeBackendClient(
            games={
                "demo-game": {
                    "slug": "demo-game",
                    "title": "Demo Game",
                    "cover_url": None,
                    "critic_score": 90,
                    "user_score": 8.5,
                }
            },
            reviews={
                "demo-game": {
                    "critic_reviews": [
                        {"publicationName": "Edge", "score": 90, "date": "2026-03-18", "quote": "Excellent."},
                        {"publicationName": "IGN", "score": 80, "date": "2026-03-17", "quote": "Very good."},
                    ],
                    "user_reviews": [],
                }
            },
        )
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=1,
            search_result_limit=8,
        )

        handler.handle_update(
            {
                "callback_query": {
                    "id": "callback-1",
                    "data": "co:demo-game",
                    "message": {"message_id": 10, "chat": {"id": 101}},
                }
            }
        )

        self.assertEqual(transport.answered_callback_queries, ["callback-1"])
        self.assertEqual(len(transport.sent_messages), 1)
        self.assertIn("媒体评论 1/2", transport.sent_messages[0]["text"])
        pagination_button = transport.sent_messages[0]["buttons"][0][0]
        self.assertEqual(pagination_button.callback_data, "cp:demo-game:2")

    def test_handle_callback_query_paginates_critic_reviews_by_editing_message(self) -> None:
        backend = _FakeBackendClient(
            games={"demo-game": {"slug": "demo-game", "title": "Demo Game", "cover_url": None}},
            reviews={
                "demo-game": {
                    "critic_reviews": [
                        {"publicationName": "Edge", "score": 90, "date": "2026-03-18", "quote": "Excellent."},
                        {"publicationName": "IGN", "score": 80, "date": "2026-03-17", "quote": "Very good."},
                    ],
                    "user_reviews": [],
                }
            },
        )
        transport = _FakeTransport()
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=1,
            search_result_limit=8,
        )

        handler.handle_update(
            {
                "callback_query": {
                    "id": "callback-2",
                    "data": "cp:demo-game:2",
                    "message": {"message_id": 22, "chat": {"id": 101}},
                }
            }
        )

        self.assertEqual(transport.answered_callback_queries, ["callback-2"])
        self.assertEqual(len(transport.edited_messages), 1)
        self.assertIn("媒体评论 2/2", transport.edited_messages[0]["text"])
        prev_button = transport.edited_messages[0]["buttons"][0][0]
        self.assertEqual(prev_button.callback_data, "cp:demo-game:1")

    def test_handle_game_detail_falls_back_to_text_when_photo_send_fails(self) -> None:
        backend = _FakeBackendClient(
            search_payload={"query": "Demo", "selected": {"slug": "demo-game"}, "matches": []},
            games={
                "demo-game": {
                    "slug": "demo-game",
                    "title": "Demo Game",
                    "cover_url": "https://example.com/demo.jpg",
                    "critic_score": 85,
                    "user_score": 7.9,
                }
            },
        )
        transport = _FakeTransport(photo_error=TelegramApiError("photo failed"))
        handler = TelegramBotHandler(
            backend_client=backend,
            transport=transport,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )

        handler.handle_update({"message": {"chat": {"id": 101}, "text": "Demo"}})

        self.assertEqual(len(transport.sent_photos), 0)
        self.assertEqual(len(transport.sent_messages), 1)
        self.assertIn("Demo Game", transport.sent_messages[0]["text"])


class TelegramBotLifecycleTestCase(unittest.TestCase):
    def test_rate_limited_polling_waits_for_retry_after(self) -> None:
        stop_event = _RecordingStopEvent()

        class _RateLimitedTransport:
            def get_updates(self, *, offset, timeout):
                raise TelegramApiError("Too Many Requests: retry after 5", status_code=429, retry_after=5.0)

            def close(self) -> None:
                return None

            def send_message(self, *, chat_id: int, text: str, buttons=()):
                return {"chat_id": chat_id, "text": text, "buttons": buttons}

            def send_photo(self, *, chat_id: int, photo_url: str, caption: str, buttons=()):
                return {"chat_id": chat_id, "photo_url": photo_url, "caption": caption, "buttons": buttons}

            def edit_message_text(self, *, chat_id: int, message_id: int, text: str, buttons=()):
                return {"chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}

            def answer_callback_query(self, *, callback_query_id: str):
                return {"ok": True}

        config = TelegramBotConfig(
            bot_token="demo-bot-token",
            backend_base_url="http://127.0.0.1:8000",
            telegram_api_base_url="https://api.telegram.org",
            request_timeout=1.0,
            poll_timeout=30,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )
        bot = GamecriticTelegramBot(
            config=config,
            stop_event=stop_event,
            backend_client=_FakeBackendClient(),
            transport=_RateLimitedTransport(),
        )

        with self.assertLogs("gamecritic.telegram_bot", level="WARNING") as captured_logs:
            bot.serve_forever()

        self.assertEqual(stop_event.wait_calls, [5.0])
        self.assertTrue(any("retrying in 5.0s" in line for line in captured_logs.output))

    def test_close_unblocks_long_polling(self) -> None:
        poll_started = threading.Event()
        close_called = threading.Event()

        class _BlockingTransport:
            def get_updates(self, *, offset, timeout):
                poll_started.set()
                close_called.wait(1.0)
                raise TelegramApiError("transport closed")

            def close(self) -> None:
                close_called.set()

            def send_message(self, *, chat_id: int, text: str, buttons=()):
                return {"chat_id": chat_id, "text": text, "buttons": buttons}

            def send_photo(self, *, chat_id: int, photo_url: str, caption: str, buttons=()):
                return {"chat_id": chat_id, "photo_url": photo_url, "caption": caption, "buttons": buttons}

            def edit_message_text(self, *, chat_id: int, message_id: int, text: str, buttons=()):
                return {"chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}

            def answer_callback_query(self, *, callback_query_id: str):
                return {"ok": True}

        config = TelegramBotConfig(
            bot_token="demo-bot-token",
            backend_base_url="http://127.0.0.1:8000",
            telegram_api_base_url="https://api.telegram.org",
            request_timeout=1.0,
            poll_timeout=30,
            critic_reviews_per_page=5,
            search_result_limit=8,
        )
        bot = GamecriticTelegramBot(
            config=config,
            backend_client=_FakeBackendClient(),
            transport=_BlockingTransport(),
        )

        worker = threading.Thread(target=bot.serve_forever)
        worker.start()
        self.assertTrue(poll_started.wait(1.0))

        bot.close()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
