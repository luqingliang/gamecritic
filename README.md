# Gamecritic

[中文说明](./README.zh-CN.md)

Python crawler for Metacritic game data, focused on:

- game discovery from the official games sitemap
- game detail extraction from Metacritic backend JSON endpoints
- critic/user reviews pagination
- SQLite persistence for crawled data and sync checkpoints
- Excel export for crawled SQLite data
- optional cover image file download

## Requirements

- Python 3.10+

## Quick Start

```bash
# From the project root, create a local virtual environment and install the package
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .

# Start the interactive shell
gamecritic
# or: gamecritic interactive
```

## CLI Settings

`config/cli_settings.json` is the shared settings profile for the interactive shell and the
regular CLI commands.
You can edit this file directly, or update the same settings from
`gamecritic interactive` with commands such as `set <key> <value>` and `reset`.
All non-positional runtime parameters now come from this shared config file instead of
per-command CLI flags.

Parameter reference:

```jsonc
{
  // SQLite database path
  "db": "data/gamecritic.db",

  // Fetch critic reviews during `crawl` / `crawl-one`
  "include_critic_reviews": false,

  // Fetch user reviews during `crawl` / `crawl-one`
  "include_user_reviews": false,

  // Number of reviews requested per page
  "review_page_size": 50,

  // Maximum review pages fetched per game
  "max_review_pages": 1,

  // Number of concurrent workers for batch crawl tasks
  "concurrency": 4,

  // Request timeout in seconds
  "timeout": 30.0,

  // Maximum retry attempts per request
  "max_retries": 4,

  // Retry backoff interval in seconds
  "backoff": 1.5,

  // Delay between requests in seconds
  "delay": 0.2,

  // Download cover files while crawling
  "download_covers": false,

  // Directory for downloaded cover files
  "covers_dir": "data/covers",

  // Overwrite existing cover files
  "overwrite_covers": false,

  // Output path for Excel export
  "export_output": "data/excel/gamecritic_export.xlsx",

  // HTTP service bind host
  "server_host": "127.0.0.1",

  // HTTP service bind port
  "server_port": 8000
}
```

## Common Commands

```bash
# Open the interactive shell
gamecritic interactive

# Crawl all stored slugs from `game_slugs`
gamecritic crawl

# Search the local slug index by game name
gamecritic search-slug "The Legend of Zelda Breath of the Wild"

# Crawl one game by slug
gamecritic crawl-one the-legend-of-zelda-breath-of-the-wild

# Backfill reviews for all crawled games
gamecritic crawl-reviews

# Or pass an optional `[slug]` to backfill one game
gamecritic crawl-reviews the-legend-of-zelda-breath-of-the-wild

# Sync all sitemap slugs into SQLite
gamecritic sync-slugs

# Download covers for all crawled games
gamecritic download-covers

# Or pass an optional `[slug]` to download one game's cover
gamecritic download-covers the-legend-of-zelda-breath-of-the-wild

# Export SQLite data to Excel
gamecritic export-excel

# Start the HTTP API service
gamecritic serve

# Clear all project tables while keeping the schema
gamecritic clear-db
```

## HTTP API

Start the local service:

```bash
gamecritic serve
```

The service root now serves a user-facing frontend:

- `GET /`: Slug lookup homepage.
- `GET /game/<slug>`: Deep link to one game's detail view.

Available endpoints:

- `GET /api/game?slug=<slug>`: Returns one game's stored data. If the row is missing from `games`, the service crawls it, stores it, and then returns the fresh record.
- `GET /api/reviews?slug=<slug>`: Backfills critic + user reviews for the requested slug and returns the stored review payloads.

Both endpoints also accept path-style variants:

- `GET /api/games/<slug>`
- `GET /api/games/<slug>/reviews`

## Data Schema

SQLite tables:

- `games`: Stores crawled game metadata, score summaries, cover URL, and raw product/summary JSON snapshots.
- `game_slugs`: Stores the sitemap-derived slug index, including source sitemap and discovery timestamps.
- `critic_reviews`: Stores critic review records associated with each game slug.
- `user_reviews`: Stores user review records keyed by review ID and linked back to each game slug.
- `sync_state`: Stores lightweight key-value checkpoints such as sync progress markers.

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).

## Notes

- Respect target site rules and terms before large-scale crawling.
- Use moderate request rates and avoid paths disallowed by Metacritic's `robots.txt`: `https://www.metacritic.com/robots.txt`.
