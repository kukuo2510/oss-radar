import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "oss_radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id     TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    abstract     TEXT NOT NULL,
    authors      TEXT NOT NULL,
    category     TEXT,
    published_at TEXT,
    url          TEXT,
    fetched_at   TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(SCHEMA)


def upsert_papers(papers: list[dict]) -> int:
    """Insert papers, skipping ones already stored (by arxiv_id). Returns count of newly inserted rows."""
    with get_connection() as conn:
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO papers
                (arxiv_id, title, abstract, authors, category, published_at, url, fetched_at)
            VALUES
                (:arxiv_id, :title, :abstract, :authors, :category, :published_at, :url, :fetched_at)
            """,
            papers,
        )
        return cur.rowcount
