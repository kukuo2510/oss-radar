"""Generate a static HTML report summarizing the current pipeline output.

This is a dev-time sanity-check tool, NOT the final app UI (that's the PWA planned
for later, once the API layer exists). Pure HTML/CSS, no chart library, so it has
zero extra dependencies.
"""

from pathlib import Path

from db import get_connection

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "report.html"


def fetch_stats(conn):
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
    width = int(count / max_count * 100) if max_count else 0
    return (
        f'<div class="bar-row"><span class="bar-label">{label}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>'
        f'<span class="bar-count">{count}</span></div>'
    )


def rows_with_metric(items) -> str:
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td><td>{metric:,}</td></tr>'
        for title, metric, url in items
    )


def rows_with_date(items) -> str:
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td><td>{published}</td></tr>'
        for title, published, url in items
    )


def rows_trending(items) -> str:
    return "\n".join(
        f'<tr><td><a href="{url}" target="_blank">{title}</a></td>'
        f'<td>{source}</td><td>{score:.2f}</td><td>{basis}</td></tr>'
        for title, url, score, basis, source in items
    )


def render_html(source_counts, tag_counts, top_github, top_hf_models, recent_papers, trending) -> str:
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


def main() -> None:
    with get_connection() as conn:
        stats = fetch_stats(conn)
    html = render_html(*stats)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
