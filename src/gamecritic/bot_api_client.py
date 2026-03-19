from __future__ import annotations

from typing import Any

import httpx


class GamecriticBotApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class GamecriticBotApiClient:
    def __init__(self, *, base_url: str, request_timeout: float) -> None:
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("backend base URL must be a non-empty string")
        self._client = httpx.Client(base_url=normalized_base_url, timeout=request_timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GamecriticBotApiClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def search_games(self, query: str) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("query must be a non-empty string")
        return self._request_json("/api/search", params={"q": normalized_query})

    def get_game(self, slug: str) -> dict[str, Any]:
        normalized_slug = str(slug or "").strip()
        if not normalized_slug:
            raise ValueError("slug must be a non-empty string")
        return self._request_json("/api/game", params={"slug": normalized_slug})

    def get_reviews(self, slug: str) -> dict[str, Any]:
        normalized_slug = str(slug or "").strip()
        if not normalized_slug:
            raise ValueError("slug must be a non-empty string")
        return self._request_json("/api/reviews", params={"slug": normalized_slug})

    def _request_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise GamecriticBotApiError(f"request failed: {exc}") from exc

        status_code = int(response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GamecriticBotApiError("response parsing failed", status_code=status_code) from exc

        if not isinstance(payload, dict):
            raise GamecriticBotApiError("invalid API response", status_code=status_code)

        if status_code >= 400 or not payload.get("ok", False):
            message = str(payload.get("error") or f"request failed: {status_code}")
            raise GamecriticBotApiError(message, status_code=status_code)

        data = payload.get("data")
        if not isinstance(data, dict):
            raise GamecriticBotApiError("invalid API payload", status_code=status_code)
        return data
