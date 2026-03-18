from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

SEARCH_SLUG_AUTO_ACCEPT_SCORE = 0.95
SEARCH_SLUG_AMBIGUITY_MARGIN = 0.03
SEARCH_SLUG_MIN_SCORE = 0.95
SEARCH_SLUG_MAX_CANDIDATES = 5
SEARCH_SLUG_SHORTLIST_LIMIT = 100


@dataclass(frozen=True)
class SlugSearchCandidate:
    slug: str
    title: str | None
    slug_search_text: str
    title_search_text: str
    slug_acronym: str
    title_acronym: str
    slug_tokens: tuple[str, ...] = field(repr=False, compare=False)
    title_tokens: tuple[str, ...] = field(repr=False, compare=False)
    slug_token_set: frozenset[str] = field(repr=False, compare=False)
    title_token_set: frozenset[str] = field(repr=False, compare=False)


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


@dataclass(frozen=True)
class SlugSearchQuery:
    raw: str
    search_text: str
    compact_text: str
    slug_text: str
    tokens: tuple[str, ...]
    token_set: frozenset[str]


def normalize_search_text(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_search_acronym(value: object) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[_\W]+", "", text, flags=re.UNICODE).strip()


def slug_text(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip()


def _tokenize_normalized_search_text(normalized_text: str) -> tuple[str, ...]:
    if not normalized_text:
        return ()
    return tuple(token for token in normalized_text.split(" ") if token)


def search_token_list(text: str) -> list[str]:
    normalized = normalize_search_text(text)
    return list(_tokenize_normalized_search_text(normalized))


def search_tokens(text: str) -> set[str]:
    return set(search_token_list(text))


def search_acronym_from_text(text: object) -> str:
    normalized = normalize_search_text(text)
    return "".join(token[0] for token in _tokenize_normalized_search_text(normalized))


def compute_slug_search_fields(*, slug: str, title: str | None) -> dict[str, str]:
    normalized_slug = str(slug).strip()
    normalized_title = str(title).strip() if title is not None else ""
    slug_search_text = normalize_search_text(slug_text(normalized_slug))
    title_search_text = normalize_search_text(normalized_title)
    return {
        "slug_search_text": slug_search_text,
        "title_search_text": title_search_text,
        "slug_acronym": search_acronym_from_text(slug_search_text),
        "title_acronym": search_acronym_from_text(title_search_text),
    }


def build_slug_search_candidate(
    *,
    slug: str,
    title: str | None,
    slug_search_text: str | None = None,
    title_search_text: str | None = None,
    slug_acronym: str | None = None,
    title_acronym: str | None = None,
) -> SlugSearchCandidate | None:
    normalized_slug = str(slug).strip()
    if not normalized_slug:
        return None

    normalized_title = str(title).strip() if title is not None else None
    computed_fields: dict[str, str] | None = None

    def _computed_field(name: str) -> str:
        nonlocal computed_fields
        if computed_fields is None:
            computed_fields = compute_slug_search_fields(slug=normalized_slug, title=normalized_title)
        return computed_fields[name]

    normalized_slug_search_text = (
        str(slug_search_text).strip()
        if slug_search_text is not None
        else _computed_field("slug_search_text")
    )
    normalized_title_search_text = (
        str(title_search_text).strip()
        if title_search_text is not None
        else _computed_field("title_search_text")
    )
    normalized_slug_acronym = (
        str(slug_acronym).strip()
        if slug_acronym is not None
        else _computed_field("slug_acronym")
    )
    normalized_title_acronym = (
        str(title_acronym).strip()
        if title_acronym is not None
        else _computed_field("title_acronym")
    )
    slug_tokens = _tokenize_normalized_search_text(normalized_slug_search_text)
    title_tokens = _tokenize_normalized_search_text(normalized_title_search_text)

    return SlugSearchCandidate(
        slug=normalized_slug,
        title=normalized_title or None,
        slug_search_text=normalized_slug_search_text,
        title_search_text=normalized_title_search_text,
        slug_acronym=normalized_slug_acronym,
        title_acronym=normalized_title_acronym,
        slug_tokens=slug_tokens,
        title_tokens=title_tokens,
        slug_token_set=frozenset(slug_tokens),
        title_token_set=frozenset(title_tokens),
    )


def build_slug_search_query(query: str) -> SlugSearchQuery:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("search query must be a non-empty string")
    search_text = normalize_search_text(normalized_query)
    tokens = _tokenize_normalized_search_text(search_text)
    return SlugSearchQuery(
        raw=normalized_query,
        search_text=search_text,
        compact_text=normalize_search_acronym(normalized_query),
        slug_text=search_text.replace(" ", "-"),
        tokens=tokens,
        token_set=frozenset(tokens),
    )


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


def abbreviation_match_score(
    *,
    query_tokens: Sequence[str],
    candidate_tokens: Sequence[str],
    candidate_acronym: str,
) -> float:
    if not query_tokens or len(candidate_tokens) < 2:
        return 0.0
    if len(query_tokens) == 1 and query_tokens[0] == candidate_acronym:
        return 0.995

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


def text_match_score(
    *,
    query_search_text: str,
    query_token_set: frozenset[str],
    candidate_search_text: str,
    candidate_token_set: frozenset[str],
) -> float:
    if not query_search_text or not candidate_search_text:
        return 0.0
    if query_search_text == candidate_search_text:
        return 1.0

    shared_tokens = query_token_set & candidate_token_set
    union_tokens = query_token_set | candidate_token_set
    jaccard = len(shared_tokens) / len(union_tokens) if union_tokens else 0.0
    coverage = len(shared_tokens) / len(query_token_set) if query_token_set else 0.0
    sequence_ratio = SequenceMatcher(None, query_search_text, candidate_search_text).ratio()

    score = max(sequence_ratio, jaccard * 0.9, coverage * 0.88)
    if candidate_search_text.startswith(query_search_text) or query_search_text.startswith(candidate_search_text):
        score = max(score, 0.9 + (coverage * 0.08))
    elif query_search_text in candidate_search_text or candidate_search_text in query_search_text:
        score = max(score, 0.84 + (coverage * 0.08))
    return min(score, 0.999)


def score_slug_search_candidate(
    *,
    query: SlugSearchQuery,
    candidate: SlugSearchCandidate,
) -> SlugSearchMatch | None:
    if query.search_text and query.slug_text == candidate.slug.casefold():
        return SlugSearchMatch(slug=candidate.slug, title=candidate.title, score=1.0, matched_by="slug")

    title_score = text_match_score(
        query_search_text=query.search_text,
        query_token_set=query.token_set,
        candidate_search_text=candidate.title_search_text,
        candidate_token_set=candidate.title_token_set,
    )
    slug_score = text_match_score(
        query_search_text=query.search_text,
        query_token_set=query.token_set,
        candidate_search_text=candidate.slug_search_text,
        candidate_token_set=candidate.slug_token_set,
    )
    title_abbreviation_score = abbreviation_match_score(
        query_tokens=query.tokens,
        candidate_tokens=candidate.title_tokens,
        candidate_acronym=candidate.title_acronym,
    )
    slug_abbreviation_score = abbreviation_match_score(
        query_tokens=query.tokens,
        candidate_tokens=candidate.slug_tokens,
        candidate_acronym=candidate.slug_acronym,
    )

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

    if matched_by == "title" and candidate.title:
        best_score = min(0.999, best_score + 0.01)

    if best_score < SEARCH_SLUG_MIN_SCORE:
        return None

    return SlugSearchMatch(
        slug=candidate.slug,
        title=candidate.title,
        score=best_score,
        matched_by=matched_by,
    )


def find_slug_search_matches(
    candidates: Sequence[SlugSearchCandidate],
    query: str,
    *,
    limit: int | None = SEARCH_SLUG_MAX_CANDIDATES,
) -> tuple[list[SlugSearchMatch], int]:
    query_context = build_slug_search_query(query)
    return _find_slug_search_matches(candidates, query_context, limit=limit)


def _find_slug_search_matches(
    candidates: Sequence[SlugSearchCandidate],
    query: SlugSearchQuery,
    *,
    limit: int | None = SEARCH_SLUG_MAX_CANDIDATES,
) -> tuple[list[SlugSearchMatch], int]:
    matches: list[SlugSearchMatch] = []
    for candidate in candidates:
        match = score_slug_search_candidate(query=query, candidate=candidate)
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
    candidates: Sequence[SlugSearchCandidate],
    query: str,
    *,
    limit: int | None = SEARCH_SLUG_MAX_CANDIDATES,
) -> SlugSearchResult:
    query_context = build_slug_search_query(query)
    matches, total_matches = _find_slug_search_matches(candidates, query_context, limit=limit)
    return SlugSearchResult(
        query=query_context.raw,
        matches=matches,
        total_matches=total_matches,
        selected=select_slug_search_match(matches),
    )
