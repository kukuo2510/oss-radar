import sqlite3
from datetime import datetime, timezone
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

CREATE TABLE IF NOT EXISTS embeddings (
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    model      TEXT NOT NULL,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS item_tags (
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    tag        TEXT NOT NULL,
    score      REAL NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, tag)
);

CREATE TABLE IF NOT EXISTS trend_scores (
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    score       REAL NOT NULL,
    basis       TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS interactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN ('like', 'skip')),
    created_at TEXT NOT NULL
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


def get_items_missing_embeddings() -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT items.source, items.source_id, items.title, items.description
            FROM items
            LEFT JOIN embeddings
                ON items.source = embeddings.source AND items.source_id = embeddings.source_id
            WHERE embeddings.source_id IS NULL
            """
        ).fetchall()
        return [dict(row) for row in rows]


def upsert_embeddings(rows: list[dict]) -> None:
    """Each row: source, source_id, model, vector (bytes), dim, created_at."""
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO embeddings (source, source_id, model, vector, dim, created_at)
            VALUES (:source, :source_id, :model, :vector, :dim, :created_at)
            """,
            rows,
        )


def get_all_embeddings() -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT source, source_id, vector, dim FROM embeddings").fetchall()
        return [dict(row) for row in rows]


def upsert_tags(rows: list[dict]) -> None:
    """Each row: source, source_id, tag, score, created_at."""
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO item_tags (source, source_id, tag, score, created_at)
            VALUES (:source, :source_id, :tag, :score, :created_at)
            """,
            rows,
        )


def upsert_trend_scores(rows: list[dict]) -> None:
    """Each row: source, source_id, score, basis, computed_at."""
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO trend_scores (source, source_id, score, basis, computed_at)
            VALUES (:source, :source_id, :score, :basis, :computed_at)
            """,
            rows,
        )


def get_all_trend_scores() -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT source, source_id, score FROM trend_scores").fetchall()
        return {(source, source_id): score for source, source_id, score in rows}


def record_interaction(source: str, source_id: str, action: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO interactions (source, source_id, action, created_at) VALUES (?, ?, ?, ?)",
            (source, source_id, action, datetime.now(timezone.utc).isoformat()),
        )


def get_latest_interactions() -> dict:
    """(source, source_id) -> most recent action ('like'/'skip'), so a changed mind overrides the old one."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT source, source_id, action FROM interactions
            WHERE id IN (SELECT MAX(id) FROM interactions GROUP BY source, source_id)
            """
        ).fetchall()
        return {(source, source_id): action for source, source_id, action in rows}


def get_item(source: str, source_id: str) -> dict | None:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM items WHERE source = ? AND source_id = ?", (source, source_id)
        ).fetchone()
        return dict(row) if row else None


def get_items(source: str | None = None, tag: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    query = "SELECT DISTINCT items.* FROM items"
    params: list = []
    where = []
    if tag:
        query += " JOIN item_tags ON items.source = item_tags.source AND items.source_id = item_tags.source_id"
        where.append("item_tags.tag = ?")
        params.append(tag)
    if source:
        where.append("items.source = ?")
        params.append(source)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY items.published_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_item_tags(source: str, source_id: str) -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tag, score FROM item_tags WHERE source = ? AND source_id = ? ORDER BY score DESC",
            (source, source_id),
        ).fetchall()
        return [dict(row) for row in rows]


def get_tags_with_counts() -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tag, COUNT(*) as count FROM item_tags GROUP BY tag ORDER BY count DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_top_trend_scores(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, source_id, score, basis FROM trend_scores ORDER BY score DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
