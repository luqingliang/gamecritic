from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

SEARCH_SLUG_AUTO_ACCEPT_SCORE = 0.95
SEARCH_SLUG_AMBIGUITY_MARGIN = 0.03
SEARCH_SLUG_MIN_SCORE = 0.95
SEARCH_SLUG_MAX_CANDIDATES = 5


@dataclass(frozen=True)
class SlugSearchMatch:
    slug: str
    title: str | None
    score: float
    matched_by: str


@dataclass(frozen=True)
class SlugSearchResult:
    query: str
    matches: list[SlugSearchMatch]
    total_matches: int
    selected: SlugSearchMatch | None

    @property
    def status(self) -> str:
        if self.selected is not None:
            return "matched"
        if not self.matches:
            return "no_match"
        if self.total_matches == 1:
            return "low_confidence"
        return "ambiguous"


def normalize_search_text(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def slug_text(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip()


def search_token_list(text: str) -> list[str]:
    normalized = normalize_search_text(text)
    return [token for token in normalized.split(" ") if token]


def search_tokens(text: str) -> set[str]:
    return set(search_token_list(text))


def _match_query_token_to_candidate_group(
    query_token: str,
    candidate_tokens: Sequence[str],
    start_index: int,
) -> int | None:
    if len(query_token) <= 1:
        return None

    acronym = ""
    for index in range(start_index, len(candidate_tokens)):
        token = candidate_tokens[index]
        if not token:
            continue
        acronym += token[0]
        if len(acronym) > len(query_token) or not query_token.startswith(acronym):
            return None
        if acronym == query_token and (index + 1 - start_index) >= 2:
            return index + 1
    return None


def abbreviation_match_score(query_text: str, candidate_text: str) -> float:
    query_tokens = search_token_list(query_text)
    candidate_tokens = search_token_list(candidate_text)
    if not query_tokens or len(candidate_tokens) < 2:
        return 0.0

    candidate_index = 0
    used_abbreviation = False
    for query_token in query_tokens:
        if candidate_index >= len(candidate_tokens):
            return 0.0
        if query_token == candidate_tokens[candidate_index]:
            candidate_index += 1
            continue

        matched_end = _match_query_token_to_candidate_group(query_token, candidate_tokens, candidate_index)
        if matched_end is None:
            return 0.0
        candidate_index = matched_end
        used_abbreviation = True

    if not used_abbreviation:
        return 0.0
    if candidate_index == len(candidate_tokens):
        return 0.995

    coverage = candidate_index / len(candidate_tokens)
    return min(0.98, 0.92 + (coverage * 0.06))


def text_match_score(query_text: str, candidate_text: str) -> float:
    normalized_query = normalize_search_text(query_text)
    normalized_candidate = normalize_search_text(candidate_text)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0

    query_tokens = search_tokens(normalized_query)
    candidate_tokens = search_tokens(normalized_candidate)
    shared_tokens = query_tokens & candidate_tokens
    union_tokens = query_tokens | candidate_tokens
    jaccard = len(shared_tokens) / len(union_tokens) if union_tokens else 0.0
    coverage = len(shared_tokens) / len(query_tokens) if query_tokens else 0.0
    sequence_ratio = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()

    score = max(sequence_ratio, jaccard * 0.9, coverage * 0.88)
    if normalized_candidate.startswith(normalized_query) or normalized_query.startswith(normalized_candidate):
        score = max(score, 0.9 + (coverage * 0.08))
    elif normalized_query in normalized_candidate or normalized_candidate in normalized_query:
        score = max(score, 0.84 + (coverage * 0.08))
    return min(score, 0.999)


def score_slug_search_candidate(
    *,
    query: str,
    slug: str,
    title: str | None,
) -> SlugSearchMatch | None:
    normalized_slug = str(slug).strip()
    if not normalized_slug:
        return None

    normalized_query = normalize_search_text(query)
    slug_query = normalized_query.replace(" ", "-")
    normalized_slug_text = slug_text(normalized_slug)

    if normalized_query and slug_query == normalized_slug.casefold():
        return SlugSearchMatch(slug=normalized_slug, title=title, score=1.0, matched_by="slug")

    title_score = text_match_score(query, title or "")
    slug_score = text_match_score(query, normalized_slug_text)
    title_abbreviation_score = abbreviation_match_score(query, title or "")
    slug_abbreviation_score = abbreviation_match_score(query, normalized_slug_text)

    match_priority = {
        "title": 3,
        "title_abbr": 2,
        "slug": 1,
        "slug_abbr": 0,
    }
    matched_by, best_score = max(
        (
            ("title", title_score),
            ("title_abbr", title_abbreviation_score),
            ("slug", slug_score),
            ("slug_abbr", slug_abbreviation_score),
        ),
        key=lambda item: (item[1], match_priority[item[0]]),
    )

    if matched_by == "title" and title:
        best_score = min(0.999, best_score + 0.01)

    if best_score < SEARCH_SLUG_MIN_SCORE:
        return None

    return SlugSearchMatch(
        slug=normalized_slug,
        title=title,
        score=best_score,
        matched_by=matched_by,
    )


def find_slug_search_matches(
    candidates: Sequence[tuple[str, str | None]],
    query: str,
    *,
    limit: int | None = SEARCH_SLUG_MAX_CANDIDATES,
) -> tuple[list[SlugSearchMatch], int]:
    matches: list[SlugSearchMatch] = []
    for slug, title in candidates:
        match = score_slug_search_candidate(query=query, slug=slug, title=title)
        if match is not None:
            matches.append(match)

    matches.sort(
        key=lambda item: (
            -item.score,
            item.title is None,
            len(item.slug),
            item.slug,
        )
    )
    total_matches = len(matches)
    if limit is None:
        return matches, total_matches
    return matches[:max(1, limit)], total_matches


def select_slug_search_match(matches: Sequence[SlugSearchMatch]) -> SlugSearchMatch | None:
    if not matches:
        return None

    best = matches[0]
    second = matches[1] if len(matches) > 1 else None
    if best.score < SEARCH_SLUG_AUTO_ACCEPT_SCORE:
        return None
    if second is None:
        return best
    if (best.score - second.score) >= SEARCH_SLUG_AMBIGUITY_MARGIN:
        return best
    return None


def format_slug_search_match(match: SlugSearchMatch) -> str:
    details = [f"score={match.score:.3f}", f"matched_by={match.matched_by}"]
    if match.title:
        details.insert(0, f"title={match.title}")
    return f"{match.slug}  # " + " ".join(details)


def search_slug_candidates(
    candidates: Sequence[tuple[str, str | None]],
    query: str,
    *,
    limit: int | None = SEARCH_SLUG_MAX_CANDIDATES,
) -> SlugSearchResult:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("search query must be a non-empty string")

    matches, total_matches = find_slug_search_matches(candidates, normalized_query, limit=limit)
    return SlugSearchResult(
        query=normalized_query,
        matches=matches,
        total_matches=total_matches,
        selected=select_slug_search_match(matches),
    )
