"""幫每個項目（GitHub repo、HuggingFace model/dataset）算出一個 0~1 的熱度分數。

分數是根據指標（star 數/下載數）「隨時間變化的成長率」計算，而不是絕對數值 ——
這樣一個這週從 10 顆星暴增到 200 顆星的 repo，排名會贏過一個已經穩定在 5000 顆星
但一整年沒什麼變化的 repo。要算成長率，至少需要兩筆時間點不同的快照，
這些快照就是排程器（scheduler）每天執行時持續累積進 `metric_snapshots` 表的。

冷啟動情境：如果某個項目目前只有一筆快照（例如剛完成第一次擷取、還沒等到排程器
跑第二天可以拿來比較），就沒有辦法算成長率。這種情況會退回用「原始指標的
百分位排名」代替，這樣才不會讓這些還在累積歷史資料的新項目，在熱度排行裡完全被排除。

arXiv 論文完全不參與熱度計算：它們沒有熱門度指標（`metric` 固定是 None），
自然也就沒有東西可以拿來算成長率。
"""

from datetime import datetime, timezone

from db import get_connection, init_db, upsert_trend_scores

MIN_SNAPSHOTS_FOR_GROWTH = 2
SCORABLE_SOURCES = ("github", "huggingface_models", "huggingface_datasets")


def growth_rate(points: list[tuple[str, int]]) -> float:
    """points: [(snapshot_at ISO 字串, metric), ...]，已依時間排序，長度至少為 2。

    回傳「第一筆快照」與「最後一筆快照」之間，指標平均每天的變化量。
    """
    first_at, first_metric = points[0]
    last_at, last_metric = points[-1]
    days_elapsed = (datetime.fromisoformat(last_at) - datetime.fromisoformat(first_at)).total_seconds() / 86400
    # 把時間差下限設為 1 小時（1/24 天），避免同一天內重複執行時，時間差趨近於 0
    # 導致除以幾乎是 0 的數字，算出離譜的暴衝數值。
    days_elapsed = max(days_elapsed, 1 / 24)
    return (last_metric - first_metric) / days_elapsed


def percentile_ranks(id_to_value: dict) -> dict:
    """把「id -> 數值」轉成「id -> 百分位排名（0~1）」，數值愈大排名愈接近 1。"""
    if not id_to_value:
        return {}
    ordered = sorted(id_to_value.items(), key=lambda pair: pair[1])
    n = len(ordered)
    if n == 1:
        # 只有一筆資料時沒有「相對排名」的概念，直接給滿分，
        # 避免除以 (n - 1) = 0 造成錯誤。
        return {ordered[0][0]: 1.0}
    return {key: i / (n - 1) for i, (key, _value) in enumerate(ordered)}


def compute_for_source(conn, source: str) -> list[dict]:
    """計算單一來源（例如 "github"）底下所有項目的熱度分數。

    先把每個項目的歷史快照依時間排序整理好，快照數量足夠的走「成長率」路線，
    不夠的走「冷啟動」路線；兩組分數各自轉成百分位排名後再合併回傳。
    """
    snapshot_rows = conn.execute(
        "SELECT source_id, metric, snapshot_at FROM metric_snapshots WHERE source = ? ORDER BY snapshot_at",
        (source,),
    ).fetchall()

    history: dict[str, list[tuple[str, int]]] = {}
    for source_id, metric, snapshot_at in snapshot_rows:
        history.setdefault(source_id, []).append((snapshot_at, metric))

    growth_values, cold_start_values = {}, {}
    for source_id, points in history.items():
        if len(points) >= MIN_SNAPSHOTS_FOR_GROWTH:
            growth_values[source_id] = growth_rate(points)
        else:
            cold_start_values[source_id] = points[-1][1]

    # 成長率與冷啟動用的原始指標，數值量級完全不同，各自轉成百分位排名之後
    # 才有辦法放在同一個分數欄位裡比較與排序。
    growth_ranks = percentile_ranks(growth_values)
    cold_start_ranks = percentile_ranks(cold_start_values)

    computed_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for source_id, score in growth_ranks.items():
        rows.append({
            "source": source,
            "source_id": source_id,
            "score": score,
            "basis": "growth",
            "computed_at": computed_at,
        })
    for source_id, score in cold_start_ranks.items():
        rows.append({
            "source": source,
            "source_id": source_id,
            "score": score,
            "basis": "cold_start",
            "computed_at": computed_at,
        })
    return rows


def main() -> None:
    """對每個可計分的來源計算熱度分數，並整批寫入資料庫。"""
    init_db()
    all_rows = []
    with get_connection() as conn:
        for source in SCORABLE_SOURCES:
            rows = compute_for_source(conn, source)
            growth_n = sum(1 for r in rows if r["basis"] == "growth")
            cold_n = sum(1 for r in rows if r["basis"] == "cold_start")
            print(f"[{source}] scored {len(rows)} items ({growth_n} by growth, {cold_n} cold-start)")
            all_rows.extend(rows)

    upsert_trend_scores(all_rows)
    print(f"Stored {len(all_rows)} trend scores.")


if __name__ == "__main__":
    main()
