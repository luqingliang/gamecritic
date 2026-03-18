from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .slug_search import (
    SEARCH_SLUG_SHORTLIST_LIMIT,
    SlugSearchCandidate,
    build_slug_search_candidate,
    build_slug_search_query,
    compute_slug_search_fields,
)

LEGACY_SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY = "game_slugs_last_successful_full_sync_at"
SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY = "indexed_slugs_last_successful_full_sync_at"

APP_TABLE_NAMES = (
    "critic_reviews",
    "user_reviews",
    "games",
    "sync_state",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _json_loads(data: object | None) -> Any:
    if data is None:
        return None
    if not isinstance(data, str):
        return data
    normalized = data.strip()
    if not normalized:
        return None
    return json.loads(normalized)


def _merge_slug_search_candidates(
    games_rows: Iterable[tuple[object, object, object, object, object, object]],
) -> list[SlugSearchCandidate]:
    candidates: list[SlugSearchCandidate] = []
    for row in games_rows:
        candidate = build_slug_search_candidate(
            slug=str(row[0]),
            title=str(row[1]).strip() if row[1] is not None else None,
            slug_search_text=str(row[2]).strip() if row[2] is not None else None,
            title_search_text=str(row[3]).strip() if row[3] is not None else None,
            slug_acronym=str(row[4]).strip() if row[4] is not None else None,
            title_acronym=str(row[5]).strip() if row[5] is not None else None,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _prefix_upper_bound(prefix: str) -> str:
    if not prefix:
        return prefix
    return prefix + "\U0010FFFF"


def _candidate_row_order_clause(*, prefer_title: bool = False, prefer_exact_field: str | None = None) -> str:
    order_parts = []
    if prefer_exact_field:
        order_parts.append(f"CASE WHEN {prefer_exact_field} THEN 0 ELSE 1 END")
    if prefer_title:
        order_parts.append("CASE WHEN COALESCE(TRIM(title), '') = '' THEN 1 ELSE 0 END")
    order_parts.extend(("LENGTH(slug)", "slug"))
    return ", ".join(order_parts)


def _fetch_slug_search_rows(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
) -> list[tuple[object, object, object, object, object, object]]:
    query_context = build_slug_search_query(query)
    if not query_context.search_text or limit <= 0:
        return []

    collected_rows: list[tuple[object, object, object, object, object, object]] = []
    seen_slugs: set[str] = set()

    def collect(sql: str, params: tuple[object, ...]) -> None:
        remaining = limit - len(collected_rows)
        if remaining <= 0:
            return
        rows = conn.execute(sql, (*params, remaining)).fetchall()
        for row in rows:
            slug = str(row[0]).strip()
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            collected_rows.append(row)
            if len(collected_rows) >= limit:
                break

    base_select = """
        SELECT slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym
        FROM games
        WHERE slug IS NOT NULL AND TRIM(slug) != ''
    """

    exact_text_sql = (
        base_select
        + """
          AND (title_search_text = ? OR slug_search_text = ?)
        ORDER BY
            CASE
                WHEN title_search_text = ? THEN 0
                WHEN slug_search_text = ? THEN 1
                ELSE 2
            END,
            """
        + _candidate_row_order_clause(prefer_title=True)
        + """
        LIMIT ?
        """
    )
    collect(
        exact_text_sql,
        (
            query_context.search_text,
            query_context.search_text,
            query_context.search_text,
            query_context.search_text,
        ),
    )

    if query_context.compact_text:
        exact_acronym_sql = (
            base_select
            + """
              AND (title_acronym = ? OR slug_acronym = ?)
            ORDER BY
                CASE
                    WHEN title_acronym = ? THEN 0
                    WHEN slug_acronym = ? THEN 1
                    ELSE 2
                END,
                """
            + _candidate_row_order_clause(prefer_title=True)
            + """
            LIMIT ?
            """
        )
        collect(
            exact_acronym_sql,
            (
                query_context.compact_text,
                query_context.compact_text,
                query_context.compact_text,
                query_context.compact_text,
            ),
        )

        if len(query_context.compact_text) >= 2:
            compact_upper_bound = _prefix_upper_bound(query_context.compact_text)
            acronym_prefix_sql = (
                base_select
                + """
                  AND (
                        (title_acronym >= ? AND title_acronym < ?)
                     OR (slug_acronym >= ? AND slug_acronym < ?)
                  )
                ORDER BY
                    CASE
                        WHEN title_acronym >= ? AND title_acronym < ? THEN 0
                        WHEN slug_acronym >= ? AND slug_acronym < ? THEN 1
                        ELSE 2
                    END,
                    """
                + _candidate_row_order_clause(prefer_title=True)
                + """
                LIMIT ?
                """
            )
            collect(
                acronym_prefix_sql,
                (
                    query_context.compact_text,
                    compact_upper_bound,
                    query_context.compact_text,
                    compact_upper_bound,
                    query_context.compact_text,
                    compact_upper_bound,
                    query_context.compact_text,
                    compact_upper_bound,
                ),
            )

    prefix_upper_bound = _prefix_upper_bound(query_context.search_text)
    text_prefix_sql = (
        base_select
        + """
          AND (
                (title_search_text >= ? AND title_search_text < ?)
             OR (slug_search_text >= ? AND slug_search_text < ?)
          )
        ORDER BY
            CASE
                WHEN title_search_text >= ? AND title_search_text < ? THEN 0
                WHEN slug_search_text >= ? AND slug_search_text < ? THEN 1
                ELSE 2
            END,
            """
        + _candidate_row_order_clause(prefer_title=True)
        + """
        LIMIT ?
        """
    )
    collect(
        text_prefix_sql,
        (
            query_context.search_text,
            prefix_upper_bound,
            query_context.search_text,
            prefix_upper_bound,
            query_context.search_text,
            prefix_upper_bound,
            query_context.search_text,
            prefix_upper_bound,
        ),
    )

    token_presence_clauses = [
        "(instr(title_search_text, ?) > 0 OR instr(slug_search_text, ?) > 0)"
        for _ in query_context.tokens
    ]
    score_parts = []
    score_params: list[object] = []
    where_params: list[object] = []
    for token in query_context.tokens:
        score_parts.extend(
            (
                "CASE WHEN instr(title_search_text, ?) > 0 THEN 2 ELSE 0 END",
                "CASE WHEN instr(slug_search_text, ?) > 0 THEN 1 ELSE 0 END",
            )
        )
        score_params.extend((token, token))
        where_params.extend((token, token))

    if token_presence_clauses:
        token_score_expr = " + ".join(score_parts)
        all_tokens_sql = (
            """
            SELECT slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym
            FROM (
                SELECT
                    slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym,
                    """
            + token_score_expr
            + """
                    AS rough_score
                FROM games
                WHERE slug IS NOT NULL
                  AND TRIM(slug) != ''
                  AND """
            + " AND ".join(token_presence_clauses)
            + """
            )
            ORDER BY rough_score DESC,
                     """
            + _candidate_row_order_clause(prefer_title=True)
            + """
            LIMIT ?
            """
        )
        collect(all_tokens_sql, tuple(score_params + where_params))

        if len(query_context.tokens) > 1:
            any_tokens_sql = (
                """
                SELECT slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym
                FROM (
                    SELECT
                        slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym,
                        """
                + token_score_expr
                + """
                        AS rough_score
                    FROM games
                    WHERE slug IS NOT NULL
                      AND TRIM(slug) != ''
                      AND (
                        """
                + " OR ".join(token_presence_clauses)
                + """
                      )
                )
                ORDER BY rough_score DESC,
                         """
                + _candidate_row_order_clause(prefer_title=True)
                + """
                LIMIT ?
                """
            )
            collect(any_tokens_sql, tuple(score_params + where_params))

    return collected_rows


def _query_slug_search_candidates(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    limit: int | None = None,
) -> list[SlugSearchCandidate]:
    try:
        if query is not None:
            normalized_query = str(query).strip()
            if not normalized_query:
                games_rows = []
            else:
                games_rows = _fetch_slug_search_rows(
                    conn,
                    normalized_query,
                    limit=max(1, limit if limit is not None else SEARCH_SLUG_SHORTLIST_LIMIT),
                )
        else:
            games_rows = conn.execute(
                """
                SELECT slug, title, slug_search_text, title_search_text, slug_acronym, title_acronym
                FROM games
                WHERE slug IS NOT NULL AND TRIM(slug) != ''
                ORDER BY slug ASC
                """
            ).fetchall()
    except sqlite3.Error as exc:
        if "no such table" in str(exc).lower():
            games_rows = []
        else:
            raise

    return _merge_slug_search_candidates(games_rows)


def load_slug_search_candidates_from_db(
    db_path: str | Path,
    *,
    query: str | None = None,
    limit: int | None = None,
) -> list[SlugSearchCandidate]:
    normalized_db_path = str(db_path).strip()
    if not normalized_db_path:
        return []

    db_file = Path(normalized_db_path)
    if not db_file.is_file():
        return []

    conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return _query_slug_search_candidates(conn, query=query, limit=limit)
    finally:
        conn.close()


def _critic_review_key(review: dict) -> str:
    parts = [
        str(review.get("publicationSlug") or ""),
        str(review.get("date") or ""),
        str(review.get("score") or ""),
        str(review.get("url") or ""),
        str(review.get("quote") or "")[:120],
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _user_review_key(review: dict) -> str:
    review_id = review.get("id")
    if review_id:
        return str(review_id)
    parts = [
        str(review.get("author") or ""),
        str(review.get("date") or ""),
        str(review.get("score") or ""),
        str(review.get("quote") or "")[:120],
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


class SQLiteStorage:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Shared across worker threads when concurrent crawl is enabled.
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    slug TEXT PRIMARY KEY,
                    game_url TEXT,
                    sitemap_url TEXT,
                    discovered_at TEXT,
                    last_seen_at TEXT,
                    is_crawled INTEGER NOT NULL DEFAULT 0,
                    slug_search_text TEXT NOT NULL DEFAULT '',
                    title_search_text TEXT NOT NULL DEFAULT '',
                    slug_acronym TEXT NOT NULL DEFAULT '',
                    title_acronym TEXT NOT NULL DEFAULT '',
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

                CREATE TABLE IF NOT EXISTS critic_reviews (
                    slug TEXT NOT NULL,
                    review_key TEXT NOT NULL,
                    score REAL,
                    review_date TEXT,
                    author TEXT,
                    publication_name TEXT,
                    source_url TEXT,
                    quote TEXT,
                    review_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    PRIMARY KEY (slug, review_key)
                );

                CREATE TABLE IF NOT EXISTS user_reviews (
                    review_id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL,
                    author TEXT,
                    score REAL,
                    review_date TEXT,
                    spoiler INTEGER NOT NULL DEFAULT 0,
                    quote TEXT,
                    review_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_critic_reviews_slug
                    ON critic_reviews(slug);

                CREATE INDEX IF NOT EXISTS idx_user_reviews_slug
                    ON user_reviews(slug);
                """
            )
            self._ensure_column("games", "game_url", "TEXT")
            self._ensure_column("games", "sitemap_url", "TEXT")
            self._ensure_column("games", "discovered_at", "TEXT")
            self._ensure_column("games", "last_seen_at", "TEXT")
            self._ensure_column("games", "is_crawled", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("games", "slug_search_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("games", "title_search_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("games", "slug_acronym", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("games", "title_acronym", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("games", "cover_url", "TEXT")
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_sitemap_slug
                    ON games(sitemap_url, slug)
                """
            )
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_is_crawled_slug
                    ON games(is_crawled, slug)
                """
            )
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_slug_search_text
                    ON games(slug_search_text)
                """
            )
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_title_search_text
                    ON games(title_search_text)
                """
            )
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_slug_acronym
                    ON games(slug_acronym)
                """
            )
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_games_title_acronym
                    ON games(title_acronym)
                """
            )
            self._migrate_legacy_sync_state_keys()
            self._mark_existing_games_as_crawled()
            self._backfill_slug_search_fields()
            self.conn.commit()

    def _ensure_column(self, table_name: str, column_name: str, column_type: str) -> None:
        cursor = self.conn.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {str(row[1]) for row in cursor.fetchall()}
        if column_name in existing_columns:
            return
        self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _mark_existing_games_as_crawled(self) -> None:
        self.conn.execute(
            """
            UPDATE games
            SET is_crawled = 1
            WHERE COALESCE(is_crawled, 0) = 0
              AND product_json IS NOT NULL
              AND TRIM(product_json) NOT IN ('', '{}')
            """
        )

    def _backfill_slug_search_fields(self) -> None:
        rows = self.conn.execute(
            """
            SELECT slug, title
            FROM games
            WHERE slug IS NOT NULL
              AND TRIM(slug) != ''
              AND (
                    COALESCE(TRIM(slug_search_text), '') = ''
                 OR COALESCE(TRIM(slug_acronym), '') = ''
                 OR (
                        COALESCE(TRIM(title), '') = ''
                    AND (
                            COALESCE(TRIM(title_search_text), '') != ''
                         OR COALESCE(TRIM(title_acronym), '') != ''
                    )
                 )
                 OR (
                        COALESCE(TRIM(title), '') != ''
                    AND (
                            COALESCE(TRIM(title_search_text), '') = ''
                         OR COALESCE(TRIM(title_acronym), '') = ''
                    )
                 )
              )
            """
        ).fetchall()
        if not rows:
            return

        updates = []
        for slug, title in rows:
            search_fields = compute_slug_search_fields(
                slug=str(slug),
                title=str(title).strip() if title is not None else None,
            )
            updates.append(
                {
                    "slug": str(slug),
                    **search_fields,
                }
            )

        self.conn.executemany(
            """
            UPDATE games
            SET slug_search_text = :slug_search_text,
                title_search_text = :title_search_text,
                slug_acronym = :slug_acronym,
                title_acronym = :title_acronym
            WHERE slug = :slug
            """,
            updates,
        )

    def _migrate_legacy_sync_state_keys(self) -> None:
        legacy_row = self.conn.execute(
            """
            SELECT state_value, updated_at
            FROM sync_state
            WHERE state_key = ?
            """,
            (LEGACY_SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY,),
        ).fetchone()
        if legacy_row is None:
            return

        existing_new_row = self.conn.execute(
            """
            SELECT 1
            FROM sync_state
            WHERE state_key = ?
            """,
            (SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY,),
        ).fetchone()
        if existing_new_row is None:
            self.conn.execute(
                """
                INSERT INTO sync_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                """,
                (
                    SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY,
                    str(legacy_row[0]),
                    str(legacy_row[1]),
                ),
            )
        self.conn.execute(
            "DELETE FROM sync_state WHERE state_key = ?",
            (LEGACY_SLUG_INDEX_LAST_FULL_SYNC_AT_STATE_KEY,),
        )

    def upsert_game(
        self,
        *,
        slug: str,
        product_payload: dict,
        critic_summary_payload: dict | None,
        user_summary_payload: dict | None,
        cover_url: str | None = None,
    ) -> None:
        normalized_slug = str(slug).strip()
        item = product_payload.get("data", {}).get("item", {})
        critic_summary_item = (critic_summary_payload or {}).get("data", {}).get("item", {})
        user_summary_item = (user_summary_payload or {}).get("data", {}).get("item", {})
        search_fields = compute_slug_search_fields(
            slug=normalized_slug,
            title=item.get("title"),
        )

        critic_score = critic_summary_item.get("score")
        critic_review_count = (
            critic_summary_item.get("reviewCount")
            or critic_summary_item.get("ratingsCount")
            or critic_summary_item.get("ratingCount")
        )
        user_score = user_summary_item.get("score")
        user_review_count = (
            user_summary_item.get("reviewCount")
            or user_summary_item.get("ratingsCount")
            or user_summary_item.get("ratingCount")
        )

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO games (
                    slug, is_crawled, slug_search_text, title_search_text, slug_acronym, title_acronym,
                    game_id, title, platform, release_date, premiere_year, rating,
                    critic_score, critic_review_count, user_score, user_review_count, cover_url,
                    product_json, critic_summary_json, user_summary_json, scraped_at
                ) VALUES (
                    :slug, :is_crawled, :slug_search_text, :title_search_text, :slug_acronym, :title_acronym,
                    :game_id, :title, :platform, :release_date, :premiere_year, :rating,
                    :critic_score, :critic_review_count, :user_score, :user_review_count, :cover_url,
                    :product_json, :critic_summary_json, :user_summary_json, :scraped_at
                )
                ON CONFLICT(slug) DO UPDATE SET
                    is_crawled=excluded.is_crawled,
                    slug_search_text=excluded.slug_search_text,
                    title_search_text=excluded.title_search_text,
                    slug_acronym=excluded.slug_acronym,
                    title_acronym=excluded.title_acronym,
                    game_id=excluded.game_id,
                    title=excluded.title,
                    platform=excluded.platform,
                    release_date=excluded.release_date,
                    premiere_year=excluded.premiere_year,
                    rating=excluded.rating,
                    critic_score=excluded.critic_score,
                    critic_review_count=excluded.critic_review_count,
                    user_score=excluded.user_score,
                    user_review_count=excluded.user_review_count,
                    cover_url=excluded.cover_url,
                    product_json=excluded.product_json,
                    critic_summary_json=excluded.critic_summary_json,
                    user_summary_json=excluded.user_summary_json,
                    scraped_at=excluded.scraped_at
                """,
                {
                    "slug": normalized_slug,
                    "is_crawled": 1,
                    **search_fields,
                    "game_id": item.get("id"),
                    "title": item.get("title"),
                    "platform": item.get("platform"),
                    "release_date": item.get("releaseDate"),
                    "premiere_year": item.get("premiereYear"),
                    "rating": item.get("rating"),
                    "critic_score": critic_score,
                    "critic_review_count": critic_review_count,
                    "user_score": user_score,
                    "user_review_count": user_review_count,
                    "cover_url": cover_url,
                    "product_json": _json_dumps(product_payload),
                    "critic_summary_json": _json_dumps(critic_summary_payload) if critic_summary_payload else None,
                    "user_summary_json": _json_dumps(user_summary_payload) if user_summary_payload else None,
                    "scraped_at": _utc_now_iso(),
                },
            )
            self.conn.commit()

    def upsert_critic_reviews(self, slug: str, reviews: Iterable[dict]) -> int:
        rows = []
        now = _utc_now_iso()
        for review in reviews:
            rows.append(
                {
                    "slug": slug,
                    "review_key": _critic_review_key(review),
                    "score": review.get("score"),
                    "review_date": review.get("date"),
                    "author": review.get("author"),
                    "publication_name": review.get("publicationName"),
                    "source_url": review.get("url"),
                    "quote": review.get("quote"),
                    "review_json": _json_dumps(review),
                    "scraped_at": now,
                }
            )
        if not rows:
            return 0
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO critic_reviews (
                    slug, review_key, score, review_date, author, publication_name,
                    source_url, quote, review_json, scraped_at
                ) VALUES (
                    :slug, :review_key, :score, :review_date, :author, :publication_name,
                    :source_url, :quote, :review_json, :scraped_at
                )
                ON CONFLICT(slug, review_key) DO UPDATE SET
                    score=excluded.score,
                    review_date=excluded.review_date,
                    author=excluded.author,
                    publication_name=excluded.publication_name,
                    source_url=excluded.source_url,
                    quote=excluded.quote,
                    review_json=excluded.review_json,
                    scraped_at=excluded.scraped_at
                """,
                rows,
            )
            self.conn.commit()
        return len(rows)

    def upsert_user_reviews(self, slug: str, reviews: Iterable[dict]) -> int:
        rows = []
        now = _utc_now_iso()
        for review in reviews:
            rows.append(
                {
                    "review_id": _user_review_key(review),
                    "slug": slug,
                    "author": review.get("author"),
                    "score": review.get("score"),
                    "review_date": review.get("date"),
                    "spoiler": 1 if review.get("spoiler") else 0,
                    "quote": review.get("quote"),
                    "review_json": _json_dumps(review),
                    "scraped_at": now,
                }
            )
        if not rows:
            return 0
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO user_reviews (
                    review_id, slug, author, score, review_date, spoiler, quote, review_json, scraped_at
                ) VALUES (
                    :review_id, :slug, :author, :score, :review_date, :spoiler, :quote, :review_json, :scraped_at
                )
                ON CONFLICT(review_id) DO UPDATE SET
                    slug=excluded.slug,
                    author=excluded.author,
                    score=excluded.score,
                    review_date=excluded.review_date,
                    spoiler=excluded.spoiler,
                    quote=excluded.quote,
                    review_json=excluded.review_json,
                    scraped_at=excluded.scraped_at
                """,
                rows,
            )
            self.conn.commit()
        return len(rows)

    def upsert_indexed_slugs(self, indexed_slugs: Iterable[tuple[str, str, str]]) -> tuple[int, int, int]:
        now = _utc_now_iso()
        row_by_slug: dict[str, dict[str, str]] = {}
        for slug, game_url, sitemap_url in indexed_slugs:
            normalized_slug = str(slug).strip()
            if not normalized_slug:
                continue
            search_fields = compute_slug_search_fields(slug=normalized_slug, title=None)
            row_by_slug[normalized_slug] = {
                "slug": normalized_slug,
                "game_url": str(game_url),
                "sitemap_url": str(sitemap_url),
                "discovered_at": now,
                "last_seen_at": now,
                **search_fields,
            }

        rows = list(row_by_slug.values())
        if not rows:
            return 0, 0, 0

        placeholders = ",".join("?" for _ in rows)
        with self._lock:
            cursor = self.conn.execute(
                f"SELECT slug FROM games WHERE slug IN ({placeholders})",
                tuple(row["slug"] for row in rows),
            )
            existing_slugs = {str(row[0]) for row in cursor.fetchall()}
            self.conn.executemany(
                """
                INSERT INTO games (
                    slug, game_url, sitemap_url, discovered_at, last_seen_at, is_crawled,
                    slug_search_text, title_search_text, slug_acronym, title_acronym, product_json, scraped_at
                ) VALUES (
                    :slug, :game_url, :sitemap_url, :discovered_at, :last_seen_at, 0,
                    :slug_search_text, :title_search_text, :slug_acronym, :title_acronym, '{}', :scraped_at
                )
                ON CONFLICT(slug) DO UPDATE SET
                    game_url=excluded.game_url,
                    sitemap_url=excluded.sitemap_url,
                    slug_search_text=excluded.slug_search_text,
                    slug_acronym=excluded.slug_acronym,
                    discovered_at=COALESCE(games.discovered_at, excluded.discovered_at),
                    last_seen_at=excluded.last_seen_at
                """,
                [{**row, "scraped_at": now} for row in rows],
            )
            self.conn.commit()

        inserted = sum(1 for row in rows if row["slug"] not in existing_slugs)
        updated = len(rows) - inserted
        return len(rows), inserted, updated

    def list_indexed_slugs(
        self,
    ) -> list[str]:
        query = """
            SELECT slug
            FROM games
            WHERE sitemap_url IS NOT NULL AND TRIM(sitemap_url) != ''
            ORDER BY sitemap_url ASC, slug ASC
        """

        with self._lock:
            cursor = self.conn.execute(query)
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]

    def list_crawled_slugs(
        self,
        *,
        slug: str | None = None,
    ) -> list[str]:
        params: tuple[object, ...] = ()
        query = """
            SELECT slug
            FROM games
            WHERE slug IS NOT NULL AND TRIM(slug) != ''
              AND is_crawled = 1
        """
        if slug is not None:
            normalized_slug = slug.strip()
            if not normalized_slug:
                return []
            query += " AND slug = ?"
            params = (normalized_slug,)
        query += " ORDER BY slug ASC"

        with self._lock:
            cursor = self.conn.execute(query, params)
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]

    def list_slug_search_candidates(
        self,
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[SlugSearchCandidate]:
        with self._lock:
            return _query_slug_search_candidates(self.conn, query=query, limit=limit)

    def count_rows(self, table_name: str) -> int:
        with self._lock:
            cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            return int(cursor.fetchone()[0])

    def count_indexed_slugs(self) -> int:
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM games
                WHERE sitemap_url IS NOT NULL AND TRIM(sitemap_url) != ''
                """
            )
            return int(cursor.fetchone()[0])

    def count_crawled_games(self) -> int:
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM games
                WHERE is_crawled = 1
                """
            )
            return int(cursor.fetchone()[0])

    def clear_all_tables(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock:
            for table_name in APP_TABLE_NAMES:
                cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                counts[table_name] = int(cursor.fetchone()[0])
            for table_name in APP_TABLE_NAMES:
                self.conn.execute(f"DELETE FROM {table_name}")
            self.conn.commit()
        return counts

    def list_game_cover_urls(
        self,
        *,
        slug: str | None = None,
    ) -> list[tuple[str, str]]:
        params: tuple[object, ...] = ()
        query = """
            SELECT slug, cover_url
            FROM games
            WHERE cover_url IS NOT NULL AND TRIM(cover_url) != ''
        """
        if slug is not None:
            normalized_slug = slug.strip()
            if not normalized_slug:
                return []
            query += " AND slug = ?"
            params = (normalized_slug,)
        query += " ORDER BY slug ASC"

        with self._lock:
            cursor = self.conn.execute(query, params)
            rows = cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def get_game(self, slug: str) -> dict[str, Any] | None:
        normalized_slug = slug.strip()
        if not normalized_slug:
            return None

        with self._lock:
            row = self.conn.execute(
                """
                SELECT
                    slug,
                    game_url,
                    sitemap_url,
                    discovered_at,
                    last_seen_at,
                    game_id,
                    title,
                    platform,
                    release_date,
                    premiere_year,
                    rating,
                    critic_score,
                    critic_review_count,
                    user_score,
                    user_review_count,
                    cover_url,
                    product_json,
                    critic_summary_json,
                    user_summary_json,
                    scraped_at
                FROM games
                WHERE slug = ?
                  AND is_crawled = 1
                """,
                (normalized_slug,),
            ).fetchone()

        if row is None:
            return None

        return {
            "slug": str(row[0]),
            "game_url": row[1],
            "sitemap_url": row[2],
            "discovered_at": row[3],
            "last_seen_at": row[4],
            "game_id": row[5],
            "title": row[6],
            "platform": row[7],
            "release_date": row[8],
            "premiere_year": row[9],
            "rating": row[10],
            "critic_score": row[11],
            "critic_review_count": row[12],
            "user_score": row[13],
            "user_review_count": row[14],
            "cover_url": row[15],
            "product": _json_loads(row[16]),
            "critic_summary": _json_loads(row[17]),
            "user_summary": _json_loads(row[18]),
            "scraped_at": row[19],
        }

    def list_critic_review_payloads(
        self,
        slug: str,
    ) -> list[dict[str, Any]]:
        normalized_slug = slug.strip()
        if not normalized_slug:
            return []

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT review_json
                FROM critic_reviews
                WHERE slug = ?
                ORDER BY review_date DESC, review_key ASC
                """,
                (normalized_slug,),
            ).fetchall()
        return [payload for payload in (_json_loads(row[0]) for row in rows) if isinstance(payload, dict)]

    def list_user_review_payloads(
        self,
        slug: str,
    ) -> list[dict[str, Any]]:
        normalized_slug = slug.strip()
        if not normalized_slug:
            return []

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT review_json
                FROM user_reviews
                WHERE slug = ?
                ORDER BY review_date DESC, review_id ASC
                """,
                (normalized_slug,),
            ).fetchall()
        return [payload for payload in (_json_loads(row[0]) for row in rows) if isinstance(payload, dict)]

    def get_state(self, key: str) -> str | None:
        with self._lock:
            cursor = self.conn.execute(
                "SELECT state_value FROM sync_state WHERE state_key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return str(row[0])

    def set_state(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO sync_state (state_key, state_value, updated_at)
                VALUES (:state_key, :state_value, :updated_at)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                {
                    "state_key": key,
                    "state_value": value,
                    "updated_at": _utc_now_iso(),
                },
            )
            self.conn.commit()
