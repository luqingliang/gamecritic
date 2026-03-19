from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from .bot_callbacks import (
    build_critic_reviews_open_callback,
    build_critic_reviews_page_callback,
    build_game_detail_callback,
)


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class RenderedTelegramMessage:
    text: str
    buttons: tuple[tuple[InlineButton, ...], ...] = ()
    photo_url: str | None = None


def render_start_message() -> RenderedTelegramMessage:
    return RenderedTelegramMessage(
        text=(
            "欢迎使用 Gamecritic Telegram 机器人。\n"
            "直接发送游戏名即可查询。\n"
            "当前支持：游戏搜索、详情查看、媒体评论分页。"
        )
    )


def render_search_results_message(
    *,
    query: str,
    matches: list[dict[str, Any]],
    result_limit: int,
) -> RenderedTelegramMessage:
    limited_matches = matches[: max(1, int(result_limit))]
    lines = [f"搜索结果：{query}", "请选择一个游戏："]
    buttons: list[tuple[InlineButton, ...]] = []
    for match in limited_matches:
        title = str(match.get("title") or match.get("slug") or "未知游戏").strip()
        buttons.append((InlineButton(text=title[:64], callback_data=build_game_detail_callback(str(match["slug"]))),))
    return RenderedTelegramMessage(text="\n".join(lines), buttons=tuple(buttons))


def render_no_results_message(query: str) -> RenderedTelegramMessage:
    return RenderedTelegramMessage(text=f"未找到匹配游戏：{query}")


def render_error_message(message: str) -> RenderedTelegramMessage:
    normalized = str(message or "").strip() or "请求失败，请稍后再试。"
    return RenderedTelegramMessage(text=normalized)


def _display_score(value: object) -> str:
    if value in (None, ""):
        return "-"
    return str(value)


def render_game_details_message(game: dict[str, Any]) -> RenderedTelegramMessage:
    slug = str(game.get("slug") or "").strip()
    title = str(game.get("title") or slug or "未知游戏").strip()
    lines = [title]

    platform = str(game.get("platform") or "").strip()
    if platform:
        lines.append(f"平台：{platform}")

    release_date = str(game.get("release_date") or "").strip()
    if release_date:
        lines.append(f"发售时间：{release_date}")

    lines.append(f"媒体评分：{_display_score(game.get('critic_score'))}")
    lines.append(f"用户评分：{_display_score(game.get('user_score'))}")

    critic_count = game.get("critic_review_count")
    if critic_count not in (None, ""):
        lines.append(f"媒体评论数：{critic_count}")

    return RenderedTelegramMessage(
        text="\n".join(lines),
        buttons=((InlineButton(text="媒体评论", callback_data=build_critic_reviews_open_callback(slug)),),),
        photo_url=str(game.get("cover_url") or "").strip() or None,
    )


def _review_source(review: dict[str, Any]) -> str:
    return str(review.get("publicationName") or review.get("author") or "Unknown").strip() or "Unknown"


def _review_date(review: dict[str, Any]) -> str:
    return str(review.get("date") or review.get("reviewDate") or "").strip()


def _review_quote(review: dict[str, Any]) -> str:
    quote = str(review.get("quote") or review.get("blurb") or review.get("summary") or "").strip()
    if not quote:
        return "无摘要。"
    if len(quote) <= 220:
        return quote
    return f"{quote[:217].rstrip()}..."


def render_critic_reviews_message(
    *,
    slug: str,
    game_title: str,
    reviews: list[dict[str, Any]],
    page: int,
    per_page: int,
) -> RenderedTelegramMessage:
    normalized_page_size = max(1, int(per_page))
    title = str(game_title or slug or "未知游戏").strip()
    total_reviews = len(reviews)
    total_pages = max(1, ceil(total_reviews / normalized_page_size)) if total_reviews else 1
    current_page = min(max(1, int(page)), total_pages)

    if not reviews:
        return RenderedTelegramMessage(
            text=f"{title}\n\n暂无媒体评论。",
            buttons=((InlineButton(text="查看详情", callback_data=build_game_detail_callback(slug)),),),
        )

    start = (current_page - 1) * normalized_page_size
    end = start + normalized_page_size
    page_items = reviews[start:end]

    lines = [f"{title}", f"媒体评论 {current_page}/{total_pages}"]
    for index, review in enumerate(page_items, start=start + 1):
        line = f"{index}. {_review_source(review)}"
        score = review.get("score")
        if score not in (None, ""):
            line = f"{line} · {score}"
        lines.append(line)
        review_date = _review_date(review)
        if review_date:
            lines.append(review_date)
        lines.append(_review_quote(review))
        lines.append("")

    while lines and not lines[-1]:
        lines.pop()

    button_rows: list[tuple[InlineButton, ...]] = []
    pagination_buttons: list[InlineButton] = []
    if current_page > 1:
        pagination_buttons.append(
            InlineButton(text="上一页", callback_data=build_critic_reviews_page_callback(slug, current_page - 1))
        )
    if current_page < total_pages:
        pagination_buttons.append(
            InlineButton(text="下一页", callback_data=build_critic_reviews_page_callback(slug, current_page + 1))
        )
    if pagination_buttons:
        button_rows.append(tuple(pagination_buttons))
    button_rows.append((InlineButton(text="查看详情", callback_data=build_game_detail_callback(slug)),))
    return RenderedTelegramMessage(text="\n".join(lines), buttons=tuple(button_rows))
