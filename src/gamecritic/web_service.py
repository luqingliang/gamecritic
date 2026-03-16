from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, ContextManager
from urllib.parse import parse_qs, unquote, urlsplit

from .scraper import MetacriticScraper
from .storage import SQLiteStorage

logger = logging.getLogger(__name__)
WEBUI_DIR = Path(__file__).with_name("webui")
STATIC_FILE_ROUTES = {
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class WebServiceError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = message


@dataclass(frozen=True)
class WebServiceConfig:
    host: str
    port: int
    include_critic_reviews: bool
    include_user_reviews: bool
    review_page_size: int
    max_review_pages: int | None


def _write_json_response(handler: BaseHTTPRequestHandler, *, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _write_bytes_response(
        handler,
        status=status,
        content_type="application/json; charset=utf-8",
        body=body,
    )


def _write_bytes_response(
    handler: BaseHTTPRequestHandler,
    *,
    status: int,
    content_type: str,
    body: bytes,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _normalize_slug(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise WebServiceError(HTTPStatus.BAD_REQUEST, "slug query parameter is required")
    return normalized


def _request_route_and_slug(path: str) -> tuple[str, str | None]:
    parsed = urlsplit(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    normalized_path = parsed.path.rstrip("/") or "/"

    if normalized_path == "/":
        return "index", None
    if normalized_path == "/api/game":
        return "game", _normalize_slug(query.get("slug", [""])[0])
    if normalized_path == "/api/reviews":
        return "reviews", _normalize_slug(query.get("slug", [""])[0])

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 3 and parts[:2] == ["api", "games"]:
        return "game", _normalize_slug(unquote(parts[2]))
    if len(parts) == 4 and parts[:2] == ["api", "games"] and parts[3] == "reviews":
        return "reviews", _normalize_slug(unquote(parts[2]))

    raise WebServiceError(HTTPStatus.NOT_FOUND, f"unknown endpoint: {parsed.path}")


class _GamecriticHTTPServer(HTTPServer):
    allow_reuse_address = True


class GamecriticWebService:
    def __init__(
        self,
        *,
        db_path: str,
        config: WebServiceConfig,
        client_factory: Callable[[], ContextManager[object]],
        stop_event: threading.Event | None = None,
        bind_server: bool = True,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._stop_event = stop_event
        self._server: _GamecriticHTTPServer | None = None
        server: _GamecriticHTTPServer | None = None
        try:
            if bind_server:
                server = _GamecriticHTTPServer((config.host, config.port), _GamecriticRequestHandler)
            self._storage = SQLiteStorage(db_path)
        except Exception:
            if server is not None:
                server.server_close()
            raise
        self._server = server
        if self._server is not None:
            self._server.service = self  # type: ignore[attr-defined]

    @property
    def server_address(self) -> tuple[str, int]:
        if self._server is None:
            raise RuntimeError("web service is not bound to a socket")
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def close(self) -> None:
        if self._server is not None:
            self._server.server_close()
        self._storage.close()

    def shutdown(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._server is not None:
            self._server.shutdown()

    def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("web service is not bound to a socket")
        self._server.serve_forever(poll_interval=0.05)

    def dispatch_path(self, path: str) -> tuple[int, dict[str, Any]]:
        route, slug = _request_route_and_slug(path)
        if route == "index":
            return HTTPStatus.OK, {
                "ok": True,
                "data": {
                    "service": "gamecritic",
                    "endpoints": {
                        "game": "/api/game?slug=<slug>",
                        "reviews": "/api/reviews?slug=<slug>",
                    },
                },
            }
        if slug is None:
            raise WebServiceError(HTTPStatus.BAD_REQUEST, "slug query parameter is required")

        if route == "game":
            return HTTPStatus.OK, {"ok": True, "data": self._get_or_crawl_game(slug)}
        if route == "reviews":
            return HTTPStatus.OK, {"ok": True, "data": self._get_or_crawl_reviews(slug)}
        raise WebServiceError(HTTPStatus.NOT_FOUND, f"unknown endpoint: {path}")

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(handler.path)
        if parsed.path.startswith("/api/"):
            status, payload = self.dispatch_path(handler.path)
            _write_json_response(
                handler,
                status=status,
                payload=payload,
            )
            return

        status, content_type, body = self.dispatch_frontend_path(handler.path)
        _write_bytes_response(
            handler,
            status=status,
            content_type=content_type,
            body=body,
        )

    def dispatch_frontend_path(self, path: str) -> tuple[int, str, bytes]:
        parsed = urlsplit(path)
        normalized_path = parsed.path.rstrip("/") or "/"

        if normalized_path == "/" or normalized_path.startswith("/game/"):
            return HTTPStatus.OK, "text/html; charset=utf-8", self._read_webui_file("index.html")

        route = STATIC_FILE_ROUTES.get(normalized_path)
        if route is not None:
            filename, content_type = route
            return HTTPStatus.OK, content_type, self._read_webui_file(filename)

        raise WebServiceError(HTTPStatus.NOT_FOUND, f"unknown endpoint: {parsed.path}")

    @staticmethod
    def _read_webui_file(filename: str) -> bytes:
        return (WEBUI_DIR / filename).read_bytes()

    def _get_or_crawl_game(self, slug: str) -> dict[str, Any]:
        game = self._storage.get_game(slug)
        if game is not None:
            game["auto_crawled"] = False
            return game

        with self._client_factory() as client:
            scraper = MetacriticScraper(client, self._storage, stop_event=self._stop_event)
            result = scraper.crawl_slug(
                slug,
                include_critic_reviews=False,
                include_user_reviews=False,
                review_page_size=self._config.review_page_size,
                max_review_pages=self._config.max_review_pages,
            )

        if result.stopped:
            raise WebServiceError(HTTPStatus.SERVICE_UNAVAILABLE, f"crawl interrupted for slug={slug}")

        game = self._storage.get_game(slug)
        if game is None:
            raise WebServiceError(HTTPStatus.BAD_GATEWAY, f"failed to crawl game for slug={slug}")

        game["auto_crawled"] = True
        return game

    def _get_or_crawl_reviews(self, slug: str) -> dict[str, Any]:
        with self._client_factory() as client:
            scraper = MetacriticScraper(client, self._storage, stop_event=self._stop_event)
            result = scraper.crawl_reviews_from_games(
                slug=slug,
                include_critic_reviews=True,
                include_user_reviews=True,
                review_page_size=self._config.review_page_size,
                max_review_pages=self._config.max_review_pages,
                concurrency=1,
            )

        if result.stopped:
            raise WebServiceError(HTTPStatus.SERVICE_UNAVAILABLE, f"review crawl interrupted for slug={slug}")

        failed_review_types = sorted({review_type for failed_slug, review_type in result.review_failures if failed_slug == slug})
        if failed_review_types:
            failed_types_text = ", ".join(failed_review_types)
            raise WebServiceError(HTTPStatus.BAD_GATEWAY, f"failed to crawl {failed_types_text} reviews for slug={slug}")

        game = self._storage.get_game(slug)
        if game is None and result.failed_slugs:
            raise WebServiceError(HTTPStatus.BAD_GATEWAY, f"failed to crawl reviews for slug={slug}")

        critic_reviews = self._storage.list_critic_review_payloads(slug)
        user_reviews = self._storage.list_user_review_payloads(slug)
        return {
            "slug": slug,
            "game_auto_crawled": result.games_crawled > 0,
            "critic_reviews": critic_reviews,
            "user_reviews": user_reviews,
            "counts": {
                "critic_reviews": len(critic_reviews),
                "user_reviews": len(user_reviews),
            },
        }


class _GamecriticRequestHandler(BaseHTTPRequestHandler):
    server_version = "gamecritic-web"

    def do_GET(self) -> None:  # noqa: N802
        service = getattr(self.server, "service", None)
        if not isinstance(service, GamecriticWebService):  # pragma: no cover
            _write_json_response(
                self,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                payload={"ok": False, "error": "service is not configured"},
            )
            return

        try:
            service.handle_get(self)
        except WebServiceError as exc:
            _write_json_response(
                self,
                status=exc.status_code,
                payload={"ok": False, "error": exc.message},
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("web service request failed path=%s error=%s", self.path, exc)
            _write_json_response(
                self,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                payload={"ok": False, "error": "internal server error"},
            )

    def log_message(self, format: str, *args: object) -> None:
        logger.info("http %s %s - %s", self.command, self.path, format % args)
