"""Fetch recent arXiv papers for given categories and store them in SQLite."""

from datetime import datetime, timezone

import feedparser
import requests

from db import init_db, upsert_items

ARXIV_API_URL = "http://export.arxiv.org/api/query"

# arXiv category codes: https://arxiv.org/category_taxonomy
DEFAULT_CATEGORIES = ["cs.CL", "cs.LG", "cs.AI"]


def fetch_arxiv(category: str, max_results: int = 50) -> list[dict]:
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    resp = requests.get(ARXIV_API_URL, params=params, timeout=30)
    resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    fetched_at = datetime.now(timezone.utc).isoformat()

    items = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        items.append(
            {
                "source": "arxiv",
                "source_id": arxiv_id,
                "title": " ".join(entry.title.split()),
                "description": " ".join(entry.summary.split()),
                "url": entry.link,
                "author": ", ".join(a.name for a in entry.authors),
                "category": category,
                "metric": None,  # arXiv has no built-in popularity signal
                "published_at": entry.published,
                "fetched_at": fetched_at,
            }
        )
    return items


def main() -> None:
    init_db()
    total_new = 0
    for category in DEFAULT_CATEGORIES:
        items = fetch_arxiv(category)
        new_count = upsert_items(items)
        # No record_snapshots here: arXiv items have no popularity metric to
        # track over time (metric=None), unlike GitHub stars / HF downloads.
        total_new += new_count
        print(f"[{category}] fetched {len(items)}, {new_count} new")
    print(f"Done. {total_new} new papers stored.")


if __name__ == "__main__":
    main()
