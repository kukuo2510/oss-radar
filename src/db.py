import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "oss_radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    url          TEXT NOT NULL,
    author       TEXT,
    category     TEXT,
    metric       INTEGER,
    published_at TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    metric      INTEGER NOT NULL,
    snapshot_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def upsert_items(items: list[dict]) -> int:
    """Insert items, skipping ones already stored (by source+source_id). Returns count of newly inserted rows."""
    with get_connection() as conn:
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO items
                (source, source_id, title, description, url, author, category, metric, published_at, fetched_at)
            VALUES
                (:source, :source_id, :title, :description, :url, :author, :category, :metric, :published_at, :fetched_at)
            """,
            items,
        )
        return cur.rowcount


def record_snapshots(items: list[dict]) -> None:
    """Always append a metric snapshot per item, regardless of whether the item itself is new.
    This builds the time series needed later to compute growth-rate-based trend scores."""
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO metric_snapshots (source, source_id, metric, snapshot_at)
            VALUES (:source, :source_id, :metric, :fetched_at)
            """,
            items,
        )
