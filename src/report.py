"""產生一份靜態 HTML 報表，摘要目前整條 pipeline 的執行結果。

這是開發階段用來快速檢查資料品質的小工具，**不是**正式的 App 畫面
（正式畫面是之後 API 層完成後才會做的 PWA）。純 HTML/CSS 組字串輸出，
沒有用任何圖表函式庫，所以完全不需要額外安裝套件。

注意：下面組 HTML 的字串（包含所有看得到的英文標題/說明文字）都是最終輸出的一部分，
重整時只調整 Python 程式碼的排版與補充註解，不會更動任何輸出內容，避免報表長相跑掉。
"""

from pathlib import Path

from db import get_connection
from recommend import recommend

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "report.html"


def fetch_stats(conn):
    """一次查出報表需要的所有統計資料：各來源筆數、標籤分布、各來源熱門項目、目前熱度排行。"""
    source_counts = conn.execute(
        "SELECT source, COUNT(*) FROM items GROUP BY source ORDER BY COUNT(*) DESC"
    ).fetchall()
    tag_counts = conn.execute(
        "SELECT tag, COUNT(*) FROM item_tags GROUP BY tag ORDER BY COUNT(*) DESC"
    ).fetchall()
    top_github = conn.execute(
        "SELECT title, metric, url FROM items WHERE source='github' ORDER BY metric DESC LIMIT 10"
    ).fetchall()
    top_hf_models = conn.execute(
        "SELECT title, metric, url FROM items WHERE source='huggingface_models' ORDER BY metric DESC LIMIT 10"
    ).fetchall()
    recent_papers = conn.execute(
        "SELECT title, published_at, url FROM items WHERE source='arxiv' ORDER BY published_at DESC LIMIT 10"
    ).fetchall()
    trending = conn.execute(
        """
        SELECT items.title, items.url, trend_scores.score, trend_scores.basis, items.source
        FROM trend_scores JOIN items
            ON trend_scores.source = items.source AND trend_scores.source_id = items.source_id
        ORDER BY trend_scores.score DESC
        LIMIT 15
        """
    ).fetchall()
    return source_counts, tag_counts, top_github, top_hf_models, recent_papers, trending


def bar(label: str, count: int, max_count: int) -> str:
    """畫一條簡單的橫向長條圖（純 HTML/CSS，寬度用百分比表示），用於「各來源筆數」等統計。"""
    width = int(count / max_count * 100) if max_count else 0
    return (
        f'<div class="bar-row"><span class="bar-label">{label}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>'
        f'<span class="bar-count">{count}</span></div>'
    )


def rows_with_metric(items) -> str:
    """把 (title, metric, url) 這種列資料轉成表格列 HTML，metric 用千分位格式顯示。"""
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td><td>{metric:,}</td></tr>'
        for title, metric, url in items
    )


def rows_with_date(items) -> str:
    """把 (title, published, url) 這種列資料轉成表格列 HTML，用於「最新論文」列表。"""
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td><td>{published}</td></tr>'
        for title, published, url in items
    )


def rows_trending(items) -> str:
    """把 (title, url, score, basis, source) 這種列資料轉成表格列 HTML，用於熱度/推薦列表。"""
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td>'
        f'<td>{source}</td><td>{score:.2f}</td><td>{basis}</td></tr>'
        for title, url, score, basis, source in items
    )


def render_html(source_counts, tag_counts, top_github, top_hf_models, recent_papers, trending, recommendations) -> str:
    """把所有統計資料組成完整的 HTML 報表字串。max_source / max_tag 是為了讓長條圖的
    寬度百分比是「相對於目前最大值」，而不是絕對數字。"""
    max_source = max((c for _, c in source_counts), default=1)
    max_tag = max((c for _, c in tag_counts), default=1)

    source_bars = "\n".join(bar(s, c, max_source) for s, c in source_counts)
    tag_bars = "\n".join(bar(t, c, max_tag) for t, c in tag_counts)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OSS Radar - Dev Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
h1 {{ font-size: 1.5rem; }}
h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
.bar-row {{ display: flex; align-items: center; gap: .5rem; margin: .3rem 0; font-size: .85rem; }}
.bar-label {{ width: 220px; flex-shrink: 0; }}
.bar-track {{ flex: 1; background: #eee; border-radius: 4px; height: 14px; overflow: hidden; }}
.bar-fill {{ background: #4f7cff; height: 100%; }}
.bar-count {{ width: 40px; text-align: right; flex-shrink: 0; }}
table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
td {{ padding: .3rem .4rem; border-bottom: 1px solid #eee; }}
a {{ color: #2952cc; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.note {{ color: #666; font-size: .85rem; }}
</style></head>
<body>
<h1>OSS Radar &mdash; Dev Report</h1>
<p class="note">Snapshot of the current pipeline output, for sanity-checking data quality during development.
Not the final app UI.</p>

<h2>Items by source</h2>
{source_bars}

<h2>Tag distribution (zero-shot classification)</h2>
{tag_bars}

<h2>Recommended for you</h2>
<p class="note">"personalized" blends similarity to your liked items with the trend score;
"trend_only" means no likes/skips recorded yet (cold start), so it's ranked by trend alone.</p>
<table><tr><th>Item</th><th>Source</th><th>Score</th><th>Basis</th></tr>{rows_trending(recommendations)}</table>

<h2>Trending now (growth-rate score, falls back to cold-start percentile)</h2>
<p class="note">"cold_start" means this item only has one metric snapshot so far &mdash; no growth rate
can be computed yet, needs the scheduler to run across multiple days.</p>
<table><tr><th>Item</th><th>Source</th><th>Score</th><th>Basis</th></tr>{rows_trending(trending)}</table>

<h2>Top GitHub repos (by stars)</h2>
<table>{rows_with_metric(top_github)}</table>

<h2>Top HuggingFace models (by downloads)</h2>
<table>{rows_with_metric(top_hf_models)}</table>

<h2>Most recent arXiv papers</h2>
<table>{rows_with_date(recent_papers)}</table>

</body></html>"""


def fetch_recommendations(conn) -> list[tuple]:
    """取得前 10 筆推薦結果，並補上標題與網址（方便報表直接顯示可點擊的連結）。"""
    results = recommend(top_n=10)
    rows = []
    for r in results:
        row = conn.execute(
            "SELECT title, url FROM items WHERE source = ? AND source_id = ?",
            (r["source"], r["source_id"]),
        ).fetchone()
        if row:
            rows.append((row[0], row[1], r["score"], r["basis"], r["source"]))
    return rows


def main() -> None:
    """查詢所有需要的資料、組成 HTML，最後寫入報表檔案。"""
    with get_connection() as conn:
        stats = fetch_stats(conn)
        recommendations = fetch_recommendations(conn)
    html = render_html(*stats, recommendations)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
