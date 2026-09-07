"""抓取最近建立、star 數較高的 GitHub repo，寫入 SQLite 資料庫。"""

import os
from datetime import datetime, timedelta, timezone

import requests

from db import init_db, upsert_items, record_snapshots

GITHUB_API_URL = "https://api.github.com/search/repositories"

# GitHub 沒有官方的「趨勢（trending）」API，所以這裡用近似的方式模擬：
# 搜尋「最近一段期間內建立」的 repo，並依 star 數排序。
DEFAULT_QUERIES = ["topic:llm", "topic:machine-learning", "topic:agent"]
LOOKBACK_DAYS = 14


def fetch_github(query: str, max_results: int = 50) -> list[dict]:
    """呼叫 GitHub 搜尋 API，抓出符合查詢條件、且在回溯期間內建立的 repo 清單。"""
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    # 有設定 GITHUB_TOKEN 的話就帶上，可以提高 API 呼叫的速率限制（rate limit）；
    # 沒有設定也能運作，只是未登入狀態的限制會低很多。
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
    """依序對每個預設查詢字串抓取 repo，寫入項目資料，同時記錄 star 數快照供之後計算熱度。"""
    init_db()
    total_new = 0
    for query in DEFAULT_QUERIES:
        items = fetch_github(query)
        new_count = upsert_items(items)
        # 跟 ingest_arxiv 不同，這裡每次都呼叫 record_snapshots：
        # GitHub repo 的 star 數會隨時間變化，需要持續記錄快照才能算出成長率型的熱度分數。
        record_snapshots(items)
        total_new += new_count
        print(f"[{query}] fetched {len(items)}, {new_count} new")
    print(f"Done. {total_new} new repos stored.")


if __name__ == "__main__":
    main()
