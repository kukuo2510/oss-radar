"""Compute a 0-1 trend score per item (GitHub repos, HuggingFace models/datasets).

Score is based on growth rate of the metric (stars/downloads) over time - not the
absolute value - so a repo that jumped from 10 to 200 stars this week ranks above
one that's sat at 5000 stars for a year. That needs at least two snapshots spaced
apart in time, which `metric_snapshots` accumulates as the scheduler runs daily.

Cold-start case: an item with only one snapshot so far (e.g. right after the first
ingestion run, before the scheduler has had a second day to compare against) has no
growth rate to compute. It falls back to a percentile rank of its raw metric instead,
so it isn't simply excluded from trend scoring while waiting for history to build up.

arXiv papers are skipped entirely: they have no popularity metric (`metric` is
always None), so there's nothing here to compute a trend from.
"""

from datetime import datetime, timezone

from db import get_connection, init_db, upsert_trend_scores

MIN_SNAPSHOTS_FOR_GROWTH = 2
SCORABLE_SOURCES = ("github", "huggingface_models", "huggingface_datasets")


def growth_rate(points: list[tuple[str, int]]) -> float:
    """points: [(snapshot_at ISO string, metric), ...] sorted by time, len >= 2.
    Returns metric change per day between the first and last snapshot."""
    first_at, first_metric = points[0]
    last_at, last_metric = points[-1]
    days_elapsed = (datetime.fromisoformat(last_at) - datetime.fromisoformat(first_at)).total_seconds() / 86400
    days_elapsed = max(days_elapsed, 1 / 24)  # floor at 1 hour so a same-day rerun can't divide by ~0
    return (last_metric - first_metric) / days_elapsed


def percentile_ranks(id_to_value: dict) -> dict:
    """id -> value becomes id -> percentile rank in [0, 1], higher value = higher rank."""
    if not id_to_value:
        return {}
    ordered = sorted(id_to_value.items(), key=lambda pair: pair[1])
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 1.0}
    return {key: i / (n - 1) for i, (key, _value) in enumerate(ordered)}


def compute_for_source(conn, source: str) -> list[dict]:
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

    growth_ranks = percentile_ranks(growth_values)
    cold_start_ranks = percentile_ranks(cold_start_values)

    computed_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for source_id, score in growth_ranks.items():
        rows.append({"source": source, "source_id": source_id, "score": score, "basis": "growth", "computed_at": computed_at})
    for source_id, score in cold_start_ranks.items():
        rows.append({"source": source, "source_id": source_id, "score": score, "basis": "cold_start", "computed_at": computed_at})
    return rows


def main() -> None:
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
