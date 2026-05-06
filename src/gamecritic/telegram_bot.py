from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from .bot_api_client import GamecriticBotApiClient
from .bot_handlers import TelegramBotHandler
from .bot_renderers import InlineButton

logger = logging.getLogger(__name__)


class TelegramApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class TelegramBotConfig:
    bot_token: str
    backend_base_url: str
    telegram_api_base_url: str
    request_timeout: float
    poll_timeout: int
    critic_reviews_per_page: int
    search_result_limit: int


class TelegramBotTransport:
    def __init__(
        self,
        *,
        api_base_url: str,
        bot_token: str,
        request_timeout: float,
    ) -> None:
        normalized_api_base_url = str(api_base_url or "").strip().rstrip("/")
        normalized_token = str(bot_token or "").strip()
        if not normalized_api_base_url:
            raise ValueError("telegram API base URL must be a non-empty string")
        if not normalized_token:
            raise ValueError("telegram bot token must be a non-empty string")

        self._client = httpx.Client(
            base_url=f"{normalized_api_base_url}/bot{normalized_token}",
            timeout=request_timeout,
        )

    def close(self) -> None:
        self._client.close()

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": max(0, int(timeout))}
        if offset is not None:
            payload["offset"] = int(offset)
        result = self._post("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramApiError("invalid getUpdates response")
        return [item for item in result if isinstance(item, dict)]

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        buttons: tuple[tuple[InlineButton, ...], ...] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        reply_markup = _reply_markup(buttons)
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self._post("sendMessage", payload)
        if not isinstance(result, dict):
            raise TelegramApiError("invalid sendMessage response")
        return result

    def send_photo(
        self,
        *,
        chat_id: int,
        photo_url: str,
        caption: str,
        buttons: tuple[tuple[InlineButton, ...], ...] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
        }
        reply_markup = _reply_markup(buttons)
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self._post("sendPhoto", payload)
        if not isinstance(result, dict):
            raise TelegramApiError("invalid sendPhoto response")
        return result

    def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        buttons: tuple[tuple[InlineButton, ...], ...] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        reply_markup = _reply_markup(buttons)
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self._post("editMessageText", payload)
        if not isinstance(result, dict):
            raise TelegramApiError("invalid editMessageText response")
        return result

    def answer_callback_query(self, *, callback_query_id: str) -> None:
        self._post("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def _post(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            response = self._client.post(f"/{method}", json=payload)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise TelegramApiError(f"telegram {method} request failed: {exc}") from exc

        status_code = int(response.status_code)
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramApiError("telegram response parsing failed") from exc

        if not isinstance(body, dict):
            raise TelegramApiError("invalid telegram API response")
        if status_code >= 400 or not body.get("ok", False):
            description = str(body.get("description") or f"telegram request failed: {status_code}")
            raise TelegramApiError(
                description,
                status_code=status_code,
                retry_after=_extract_retry_after(body.get("parameters")),
            )
        return body.get("result")


def _reply_markup(buttons: tuple[tuple[InlineButton, ...], ...]) -> dict[str, Any] | None:
    if not buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": button.text, "callback_data": button.callback_data} for button in row if button.text and button.callback_data]
            for row in buttons
            if row
        ]
    }


class GamecriticTelegramBot:
    def __init__(
        self,
        *,
        config: TelegramBotConfig,
        stop_event: threading.Event | None = None,
        backend_client: GamecriticBotApiClient | None = None,
        transport: TelegramBotTransport | None = None,
    ) -> None:
        self._config = config
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._backend_client = backend_client or GamecriticBotApiClient(
            base_url=config.backend_base_url,
            request_timeout=config.request_timeout,
        )
        self._transport = transport or TelegramBotTransport(
            api_base_url=config.telegram_api_base_url,
            bot_token=config.bot_token,
            request_timeout=max(config.request_timeout, config.poll_timeout + 5),
        )
        self._handler = TelegramBotHandler(
            backend_client=self._backend_client,
            transport=self._transport,
            critic_reviews_per_page=config.critic_reviews_per_page,
            search_result_limit=config.search_result_limit,
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
            self._transport.close()
            self._backend_client.close()

    def serve_forever(self) -> None:
        offset: int | None = None
        failure_streak = 0
        while not self._stop_event.is_set():
            try:
                updates = self._transport.get_updates(offset=offset, timeout=self._config.poll_timeout)
            except TelegramApiError as exc:
                if self._stop_event.is_set():
                    return
                if exc.status_code in {400, 401, 403, 404}:
                    logger.warning("telegram bot configuration rejected by Telegram: %s", exc.message)
                    return
                failure_streak += 1
                retry_delay = _poll_retry_delay(exc, failure_streak)
                logger.warning(
                    "telegram bot polling failed: %s; retrying in %.1fs (streak=%d)",
                    exc.message,
                    retry_delay,
                    failure_streak,
                )
                if self._stop_event.wait(retry_delay):
                    return
                continue

            failure_streak = 0
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                try:
                    self._handler.handle_update(update)
                except Exception:  # pragma: no cover - defensive guard for long-running loop
                    logger.exception("telegram bot update handling failed update_id=%s", update_id)


def _extract_retry_after(parameters: Any) -> float | None:
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if not isinstance(retry_after, (int, float)) or isinstance(retry_after, bool):
        return None
    return max(0.0, float(retry_after))


def _poll_retry_delay(exc: TelegramApiError, failure_streak: int) -> float:
    if exc.retry_after is not None:
        return max(1.0, exc.retry_after)

    bounded_streak = max(1, int(failure_streak))
    if exc.status_code == 409:
        return 10.0
    if exc.status_code == 429:
        return min(60.0, float(5 * bounded_streak))
    if exc.status_code is not None and exc.status_code >= 500:
        return min(30.0, float(2 ** min(bounded_streak, 4)))

    message = str(exc.message).lower()
    if "timed out" in message or "timeout" in message:
        return min(30.0, float(2 ** min(bounded_streak, 4)))
    if "server disconnected" in message:
        return min(15.0, float(2 ** min(bounded_streak, 3)))
    return min(10.0, float(1 + bounded_streak))
