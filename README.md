# metacritic-scraper-py

[中文说明](./README.zh-CN.md)

Python crawler for Metacritic game data, focused on:

- game discovery from the official games sitemap
- game detail extraction from Metacritic backend JSON endpoints
- critic/user reviews pagination
- SQLite persistence for crawled data and sync checkpoints

## Features

- Uses `https://www.metacritic.com/games.xml` as the primary game seed source.
- Crawls game detail endpoint (`Product`) and score summary endpoints.
- Crawls critic and user reviews with pagination (`offset/limit`).
- Stores normalized data + raw JSON payloads into SQLite for traceability.
- Can sync the full sitemap slug inventory into a dedicated `game_slugs` table.
- Can backfill critic/user reviews for games already stored in the `games` table.
- Includes retry + backoff for unstable network/API responses.
- Exports crawled results to Excel (`.xlsx`) for manual QA.

## Requirements

- Python 3.10+

## Install

```bash
cd /home/luqingliang/projects/metacritic-scraper-py
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## Quick Start

1) Start interactive shell (persistent session, like a REPL):

```bash
metacritic-scraper
# or: metacritic-scraper interactive
```

Interactive UI uses a fixed bottom input box (`metacritic>`) and a scrollable output pane above it.
Press `Enter` to run a command, `Ctrl-C`/`Ctrl-D` to exit.
If the session is not a TTY (for example piped input), it automatically falls back to plain REPL mode.

Inside interactive shell:

```text
show
help-zh
show-zh
clear-db
set db data/metacritic.db
set concurrency 4
crawl
crawl-reviews
export-excel data/excel/metacritic_export.xlsx
exit
```

## Quick-Start Defaults

For easier out-of-box usage, `crawl` and interactive mode now use a quick-start profile by default:

- `include_critic_reviews = false`
- `include_user_reviews = false`
- `max_review_pages = 1`
- `concurrency = 4`

`include_critic_reviews` and `include_user_reviews` only affect `crawl` / `crawl-one`.
They control whether review data is fetched at the same time as game data.
They do not affect the dedicated `crawl-reviews` command.

Full crawl now processes all slugs stored in `game_slugs` by default.

Regular command mode now reuses the same shared settings profile as interactive mode.
Per-command CLI options have been removed; if you need to change settings such as `db`,
`concurrency`, `download_covers`, or output paths, use `interactive` and `set`.
Those shared settings are persisted to `config/cli_settings.json` and reused by later
interactive and non-interactive runs.

2) Crawl one game:

```bash
metacritic-scraper crawl-one the-legend-of-zelda-breath-of-the-wild
```

3) Crawl all stored `game_slugs`:

```bash
metacritic-scraper crawl
```

4) Backfill reviews for games already stored in `games`:

```bash
metacritic-scraper crawl-reviews
```

Optional: download cover image files while crawling (disabled by default).

Use interactive mode to enable `download_covers` before running `crawl`.

```bash
metacritic-scraper interactive
```

Optional: enable concurrent workers (for example 4 workers).

Use interactive mode to change `concurrency`.

```bash
metacritic-scraper interactive
```

5) Sync all sitemap slugs into SQLite:

```bash
metacritic-scraper sync-slugs
```

6) Batch download cover image files from already crawled games:

```bash
metacritic-scraper download-covers
```

7) Export SQLite data to Excel:

```bash
metacritic-scraper export-excel
```

8) Clear all project tables while keeping the schema:

```bash
metacritic-scraper clear-db
```

## CLI Overview

```bash
metacritic-scraper --help
metacritic-scraper crawl --help
metacritic-scraper crawl-one --help
metacritic-scraper crawl-reviews --help
metacritic-scraper sync-slugs --help
metacritic-scraper download-covers --help
metacritic-scraper export-excel --help
metacritic-scraper clear-db --help
metacritic-scraper interactive --help
```

## Data Schema

SQLite tables:

- `games`
- `game_slugs`
- `critic_reviews`
- `user_reviews`
- `sync_state`

Each table stores essential normalized fields and raw JSON payloads (`*_json`) for future reprocessing.
`games.cover_url` stores the cover image URL built from product `bucketPath` (`/a/img/catalog/...`).
`game_slugs` stores the current sitemap slug index with `game_url`, `sitemap_url`, `discovered_at`, and `last_seen_at`.
`sync_state` stores lightweight checkpoints such as
`game_slugs_last_successful_full_sync_at`.

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).

## Roadmap

- [x] Crawl game details and reviews
- [x] Export results to Excel
- [x] Optional concurrent crawling (`--concurrency`)
- [x] Interactive CLI mode
- [x] Store cover URLs in `games.cover_url`
- [x] Sync sitemap slug inventory into `game_slugs`
- [x] Optional cover download during crawl (`--download-covers`)
- [x] Batch cover download from DB (`download-covers`)
- [ ] Expand to Movies
- [ ] Expand to TV Shows
- [ ] Expand to Music

## Notes

- Respect target site rules and terms before large-scale crawling.
- Use moderate request rates and avoid paths disallowed by Metacritic's `robots.txt`: `https://www.metacritic.com/robots.txt`.
