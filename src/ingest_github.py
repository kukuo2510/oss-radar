"""Fetch recently created, high-star GitHub repos and store them in SQLite."""

import os
from datetime import datetime, timedelta, timezone

import requests

from db import init_db, upsert_items, record_snapshots

GITHUB_API_URL = "https://api.github.com/search/repositories"

# GitHub has no official "trending" API, so we approximate it: search repos
# created within a recent window, sorted by stars.
DEFAULT_QUERIES = ["topic:llm", "topic:machine-learning", "topic:agent"]
LOOKBACK_DAYS = 14


def fetch_github(query: str, max_results: int = 50) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": f"{query} created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": min(max_results, 100),
    }
    resp = requests.get(GITHUB_API_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()

    fetched_at = datetime.now(timezone.utc).isoformat()
    items = []
    for repo in resp.json().get("items", []):
        items.append(
            {
                "source": "github",
                "source_id": repo["full_name"],
                "title": repo["full_name"],
                "description": repo.get("description") or "",
                "url": repo["html_url"],
                "author": repo["owner"]["login"],
                "category": repo.get("language") or "",
                "metric": repo["stargazers_count"],
                "published_at": repo["created_at"],
                "fetched_at": fetched_at,
            }
        )
    return items


def main() -> None:
    init_db()
    total_new = 0
    for query in DEFAULT_QUERIES:
        items = fetch_github(query)
        new_count = upsert_items(items)
        record_snapshots(items)
        total_new += new_count
        print(f"[{query}] fetched {len(items)}, {new_count} new")
    print(f"Done. {total_new} new repos stored.")


if __name__ == "__main__":
    main()
