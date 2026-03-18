from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
import secrets

TELEGRAM_CALLBACK_MAX_BYTES = 64
TELEGRAM_CALLBACK_CACHE_LIMIT = 4096
_CALLBACK_ACTIONS: "OrderedDict[str, TelegramCallbackAction]" = OrderedDict()


@dataclass(frozen=True)
class TelegramCallbackAction:
    kind: str
    slug: str
    page: int | None = None


def _normalize_slug(slug: str) -> str:
    normalized = str(slug or "").strip()
    if not normalized:
        raise ValueError("slug must be a non-empty string")
    return normalized


def _validate_callback_data(value: str) -> str:
    encoded_length = len(value.encode("utf-8"))
    if encoded_length > TELEGRAM_CALLBACK_MAX_BYTES:
        raise ValueError(f"callback data exceeds {TELEGRAM_CALLBACK_MAX_BYTES} bytes")
    return value


def _register_callback_action(action: TelegramCallbackAction) -> str:
    while True:
        token = f"cb:{secrets.token_urlsafe(8)}"
        if token not in _CALLBACK_ACTIONS:
            _CALLBACK_ACTIONS[token] = action
            while len(_CALLBACK_ACTIONS) > TELEGRAM_CALLBACK_CACHE_LIMIT:
                _CALLBACK_ACTIONS.popitem(last=False)
            return token


def build_game_detail_callback(slug: str) -> str:
    normalized_slug = _normalize_slug(slug)
    direct_value = f"g:{normalized_slug}"
    try:
        return _validate_callback_data(direct_value)
    except ValueError:
        return _register_callback_action(TelegramCallbackAction(kind="game", slug=normalized_slug))


def build_critic_reviews_open_callback(slug: str) -> str:
    normalized_slug = _normalize_slug(slug)
    direct_value = f"co:{normalized_slug}"
    try:
        return _validate_callback_data(direct_value)
    except ValueError:
        return _register_callback_action(TelegramCallbackAction(kind="critic_open", slug=normalized_slug, page=1))


def build_critic_reviews_page_callback(slug: str, page: int) -> str:
    normalized_slug = _normalize_slug(slug)
    if int(page) < 1:
        raise ValueError("page must be >= 1")
    direct_value = f"cp:{normalized_slug}:{int(page)}"
    try:
        return _validate_callback_data(direct_value)
    except ValueError:
        return _register_callback_action(
            TelegramCallbackAction(kind="critic_page", slug=normalized_slug, page=int(page))
        )


def parse_callback_data(data: str) -> TelegramCallbackAction | None:
    normalized = str(data or "").strip()
    if not normalized:
        return None

    if normalized.startswith("cb:"):
        return _CALLBACK_ACTIONS.get(normalized)

    if normalized.startswith("g:"):
        slug = normalized[2:].strip()
        if not slug:
            return None
        return TelegramCallbackAction(kind="game", slug=slug)

    if normalized.startswith("co:"):
        slug = normalized[3:].strip()
        if not slug:
            return None
        return TelegramCallbackAction(kind="critic_open", slug=slug, page=1)

    if normalized.startswith("cp:"):
        _, _, remainder = normalized.partition("cp:")
        slug, separator, raw_page = remainder.rpartition(":")
        if not separator or not slug.strip():
            return None
        try:
            page = int(raw_page)
        except ValueError:
            return None
        if page < 1:
            return None
        return TelegramCallbackAction(kind="critic_page", slug=slug.strip(), page=page)

    return None
