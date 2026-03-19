from __future__ import annotations

import logging
from typing import Any

from .bot_api_client import GamecriticBotApiClient, GamecriticBotApiError
from .bot_callbacks import parse_callback_data
from .bot_renderers import (
    RenderedTelegramMessage,
    render_critic_reviews_message,
    render_error_message,
    render_game_details_message,
    render_no_results_message,
    render_search_results_message,
    render_start_message,
)

logger = logging.getLogger(__name__)


class TelegramBotHandler:
    def __init__(
        self,
        *,
        backend_client: GamecriticBotApiClient,
        transport: Any,
        critic_reviews_per_page: int,
        search_result_limit: int,
    ) -> None:
        self._backend_client = backend_client
        self._transport = transport
        self._critic_reviews_per_page = max(1, int(critic_reviews_per_page))
        self._search_result_limit = max(1, int(search_result_limit))

    def handle_update(self, update: dict[str, Any]) -> None:
        callback_query = update.get("callback_query")
        if isinstance(callback_query, dict):
            self._handle_callback_query(callback_query)
            return

        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = self._extract_chat_id(message)
        if chat_id is None:
            return

        text = str(message.get("text") or "").strip()
        if not text:
            return

        if text.startswith("/start") or text.startswith("/help"):
            self._send_rendered_message(chat_id=chat_id, rendered=render_start_message())
            return

        try:
            search_payload = self._backend_client.search_games(text)
            selected = search_payload.get("selected")
            if isinstance(selected, dict) and selected.get("slug"):
                self._send_game_details(chat_id=chat_id, slug=str(selected["slug"]))
                return

            matches = search_payload.get("matches")
            if isinstance(matches, list) and matches:
                self._send_rendered_message(
                    chat_id=chat_id,
                    rendered=render_search_results_message(
                        query=str(search_payload.get("query") or text),
                        matches=[match for match in matches if isinstance(match, dict)],
                        result_limit=self._search_result_limit,
                    ),
                )
                return

            self._send_rendered_message(chat_id=chat_id, rendered=render_no_results_message(text))
        except GamecriticBotApiError as exc:
            logger.warning("telegram bot search failed query=%s: %s", text, exc.message)
            self._send_rendered_message(chat_id=chat_id, rendered=render_error_message(f"查询失败：{exc.message}"))

    def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_query_id = str(callback_query.get("id") or "").strip()
        if callback_query_id:
            self._answer_callback_query(callback_query_id)

        action = parse_callback_data(str(callback_query.get("data") or ""))
        if action is None:
            return

        message = callback_query.get("message")
        if not isinstance(message, dict):
            return

        chat_id = self._extract_chat_id(message)
        if chat_id is None:
            return

        if action.kind == "game":
            self._send_game_details(chat_id=chat_id, slug=action.slug)
            return

        if action.kind == "critic_open":
            self._send_critic_reviews(chat_id=chat_id, slug=action.slug, page=1)
            return

        if action.kind == "critic_page":
            message_id = message.get("message_id")
            if not isinstance(message_id, int):
                return
            self._edit_critic_reviews(chat_id=chat_id, message_id=message_id, slug=action.slug, page=action.page or 1)

    def _send_game_details(self, *, chat_id: int, slug: str) -> None:
        try:
            game = self._backend_client.get_game(slug)
            rendered = render_game_details_message(game)
        except GamecriticBotApiError as exc:
            logger.warning("telegram bot game lookup failed slug=%s: %s", slug, exc.message)
            self._send_rendered_message(chat_id=chat_id, rendered=render_error_message(f"获取游戏详情失败：{exc.message}"))
            return

        self._send_rendered_message(chat_id=chat_id, rendered=rendered)

    def _send_critic_reviews(self, *, chat_id: int, slug: str, page: int) -> None:
        try:
            game = self._backend_client.get_game(slug)
            reviews_payload = self._backend_client.get_reviews(slug)
            rendered = render_critic_reviews_message(
                slug=slug,
                game_title=str(game.get("title") or slug),
                reviews=self._critic_reviews_from_payload(reviews_payload),
                page=page,
                per_page=self._critic_reviews_per_page,
            )
        except GamecriticBotApiError as exc:
            logger.warning("telegram bot critic review lookup failed slug=%s: %s", slug, exc.message)
            self._send_rendered_message(chat_id=chat_id, rendered=render_error_message(f"获取媒体评论失败：{exc.message}"))
            return

        self._send_rendered_message(chat_id=chat_id, rendered=rendered)

    def _edit_critic_reviews(self, *, chat_id: int, message_id: int, slug: str, page: int) -> None:
        try:
            game = self._backend_client.get_game(slug)
            reviews_payload = self._backend_client.get_reviews(slug)
            rendered = render_critic_reviews_message(
                slug=slug,
                game_title=str(game.get("title") or slug),
                reviews=self._critic_reviews_from_payload(reviews_payload),
                page=page,
                per_page=self._critic_reviews_per_page,
            )
        except GamecriticBotApiError as exc:
            logger.warning("telegram bot critic review page failed slug=%s page=%d: %s", slug, page, exc.message)
            self._send_rendered_message(chat_id=chat_id, rendered=render_error_message(f"获取媒体评论失败：{exc.message}"))
            return

        try:
            self._transport.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=rendered.text,
                buttons=rendered.buttons,
            )
        except Exception as exc:
            logger.warning("telegram bot failed editing critic review message slug=%s page=%d: %s", slug, page, exc)
            self._send_rendered_message(chat_id=chat_id, rendered=rendered)

    @staticmethod
    def _critic_reviews_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        reviews = payload.get("critic_reviews")
        if not isinstance(reviews, list):
            return []
        return [review for review in reviews if isinstance(review, dict)]

    @staticmethod
    def _extract_chat_id(message: dict[str, Any]) -> int | None:
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        return chat_id if isinstance(chat_id, int) else None

    def _answer_callback_query(self, callback_query_id: str) -> None:
        try:
            self._transport.answer_callback_query(callback_query_id=callback_query_id)
        except Exception as exc:
            logger.warning("telegram bot failed answering callback query id=%s: %s", callback_query_id, exc)

    def _send_rendered_message(self, *, chat_id: int, rendered: RenderedTelegramMessage) -> None:
        if rendered.photo_url:
            try:
                self._transport.send_photo(
                    chat_id=chat_id,
                    photo_url=rendered.photo_url,
                    caption=rendered.text,
                    buttons=rendered.buttons,
                )
                return
            except Exception as exc:
                logger.warning("telegram bot photo send failed chat_id=%s: %s", chat_id, exc)

        self._transport.send_message(chat_id=chat_id, text=rendered.text, buttons=rendered.buttons)
