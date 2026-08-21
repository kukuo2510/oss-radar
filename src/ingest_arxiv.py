"""Fetch recent arXiv papers for given categories and store them in SQLite."""

from datetime import datetime, timezone

import feedparser
import requests

from db import init_db, upsert_papers

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

    papers = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": " ".join(entry.title.split()),
                "abstract": " ".join(entry.summary.split()),
                "authors": ", ".join(a.name for a in entry.authors),
                "category": category,
                "published_at": entry.published,
                "url": entry.link,
                "fetched_at": fetched_at,
            }
        )
    return papers


def main() -> None:
    init_db()
    total_new = 0
    for category in DEFAULT_CATEGORIES:
        papers = fetch_arxiv(category)
        new_count = upsert_papers(papers)
        total_new += new_count
        print(f"[{category}] fetched {len(papers)}, {new_count} new")
    print(f"Done. {total_new} new papers stored.")


if __name__ == "__main__":
    main()
