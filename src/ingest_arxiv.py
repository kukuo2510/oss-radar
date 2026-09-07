"""抓取指定分類下最近發表的 arXiv 論文，寫入 SQLite 資料庫。"""

from datetime import datetime, timezone

import feedparser
import requests

from db import init_db, upsert_items

ARXIV_API_URL = "http://export.arxiv.org/api/query"

# arXiv 分類代碼對照表：https://arxiv.org/category_taxonomy
DEFAULT_CATEGORIES = ["cs.CL", "cs.LG", "cs.AI"]


def fetch_arxiv(category: str, max_results: int = 50) -> list[dict]:
    """呼叫 arXiv API 抓取單一分類下最新的論文，轉換成統一格式的項目清單。"""
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    resp = requests.get(ARXIV_API_URL, params=params, timeout=30)
    resp.raise_for_status()

    # arXiv API 回傳的是 Atom feed 格式，用 feedparser 解析成好操作的物件。
    feed = feedparser.parse(resp.text)
    fetched_at = datetime.now(timezone.utc).isoformat()

    items = []
    for entry in feed.entries:
        # entry.id 長得像 "http://arxiv.org/abs/2401.12345v1"，
        # 取最後一段當作這篇論文的唯一識別碼（arxiv_id）。
        arxiv_id = entry.id.split("/abs/")[-1]
        items.append(
            {
                "source": "arxiv",
                "source_id": arxiv_id,
                # 用 " ".join(x.split()) 把標題/摘要裡多餘的換行與連續空白壓縮成單一空格，
                # arXiv 原始資料裡常見標題/摘要跨行造成排版不整齊的問題。
                "title": " ".join(entry.title.split()),
                "description": " ".join(entry.summary.split()),
                "url": entry.link,
                "author": ", ".join(a.name for a in entry.authors),
                "category": category,
                "metric": None,  # arXiv 本身沒有內建的熱門度指標（不像 GitHub star 數）
                "published_at": entry.published,
                "fetched_at": fetched_at,
            }
        )
    return items


def main() -> None:
    """依序抓取所有預設分類的論文並寫入資料庫，印出各分類與整體的新增筆數。"""
    init_db()
    total_new = 0
    for category in DEFAULT_CATEGORIES:
        items = fetch_arxiv(category)
        new_count = upsert_items(items)
        # 這裡刻意不呼叫 record_snapshots：arXiv 項目沒有像 GitHub star 數／
        # HuggingFace 下載數那種可以隨時間追蹤變化的熱門度指標（metric 固定是 None），
        # 所以沒有必要（也沒有意義）幫它記錄指標快照。
        total_new += new_count
        print(f"[{category}] fetched {len(items)}, {new_count} new")
    print(f"Done. {total_new} new papers stored.")


if __name__ == "__main__":
    main()
