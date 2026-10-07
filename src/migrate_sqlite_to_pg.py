"""一次性搬家腳本：把本機舊的 SQLite 資料庫（data/oss_radar.db）整份複製到 Postgres（Neon）。

只在 SQLite → Postgres 轉換時跑一次。目標資料表必須是空的，避免重複執行時把資料寫兩份；
搬完後會逐表比對筆數。舊的 SQLite 檔案不會被刪除（experiments/rl 還在讀它）。

用法（在 src/ 底下）：python migrate_sqlite_to_pg.py
"""

import sqlite3
from pathlib import Path

from db import get_connection, init_db

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "oss_radar.db"

# interactions 的 id 要原樣搬過去：get_latest_interactions() 靠 id 大小判斷哪一筆是最新的。
TABLES = ["items", "metric_snapshots", "embeddings", "item_tags", "trend_scores", "interactions", "narrations"]


def main() -> None:
    init_db()
    src = sqlite3.connect(SQLITE_PATH)
    with get_connection() as conn:
        for table in TABLES:
            existing = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if existing:
                raise SystemExit(f"{table} 已經有 {existing} 筆資料，為避免重複寫入而中止。")

        for table in TABLES:
            cur = src.execute(f"SELECT * FROM {table}")
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                placeholders = ", ".join(["%s"] * len(columns))
                conn.cursor().executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows
                )
            print(f"{table}: {len(rows)} rows")

        # 手動指定過 id，identity 的序號要跟上目前最大值，之後新增的互動才不會撞號。
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('interactions', 'id'), "
            "COALESCE((SELECT MAX(id) FROM interactions), 0) + 1, false)"
        )

    with get_connection() as conn:
        for table in TABLES:
            expected = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            status = "OK" if expected == actual else "MISMATCH"
            print(f"[{status}] {table}: sqlite={expected} postgres={actual}")
    src.close()


if __name__ == "__main__":
    main()
