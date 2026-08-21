"""Content-based personalized ranking.

Build a "user profile" vector from the embeddings of liked items (pulled toward
skipped items' embeddings, slightly), then rank not-yet-seen items by cosine
similarity to that profile. Final ranking blends that personalization signal with
the trend score from trend.py, so a good match that's also currently trending beats
a good match that's old news.

Cold start: with zero interactions there's no profile to build, so ranking falls back
to trend score alone - same cold-start pattern trend.py itself uses for fresh items.
"""

import numpy as np

from db import (
    get_all_embeddings,
    get_all_trend_scores,
    get_connection,
    get_latest_interactions,
    init_db,
)
from trend import percentile_ranks

PERSONALIZATION_WEIGHT = 0.6
TREND_WEIGHT = 0.4
SKIP_PENALTY = 0.3  # how much a skipped item pulls the profile away from it, relative to a like pulling toward it


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def build_user_profile(embeddings_by_key: dict, interactions: dict) -> np.ndarray | None:
    liked = [embeddings_by_key[key] for key, action in interactions.items() if action == "like" and key in embeddings_by_key]
    skipped = [embeddings_by_key[key] for key, action in interactions.items() if action == "skip" and key in embeddings_by_key]

    if not liked:
        return None

    profile = np.mean(liked, axis=0)
    if skipped:
        profile = profile - SKIP_PENALTY * np.mean(skipped, axis=0)
    return profile


def recommend(top_n: int = 20) -> list[dict]:
    embeddings_by_key = {
        (row["source"], row["source_id"]): np.frombuffer(row["vector"], dtype="float32")
        for row in get_all_embeddings()
    }
    interactions = get_latest_interactions()
    trend_scores = get_all_trend_scores()

    candidates = {key: vec for key, vec in embeddings_by_key.items() if key not in interactions}
    if not candidates:
        return []

    profile = build_user_profile(embeddings_by_key, interactions)

    if profile is None:
        ranked = sorted(candidates, key=lambda k: trend_scores.get(k, 0.0), reverse=True)[:top_n]
        return [{"source": k[0], "source_id": k[1], "score": trend_scores.get(k, 0.0), "basis": "trend_only"} for k in ranked]

    personalization_ranks = percentile_ranks({key: cosine_sim(vec, profile) for key, vec in candidates.items()})
    trend_ranks = percentile_ranks({key: trend_scores.get(key, 0.0) for key in candidates})

    combined = {
        key: PERSONALIZATION_WEIGHT * personalization_ranks[key] + TREND_WEIGHT * trend_ranks[key]
        for key in candidates
    }
    ranked = sorted(combined, key=lambda k: combined[k], reverse=True)[:top_n]
    return [{"source": k[0], "source_id": k[1], "score": combined[k], "basis": "personalized"} for k in ranked]


def main() -> None:
    init_db()
    results = recommend()
    if not results:
        print("No candidates to recommend (run embed.py first, and make sure not everything has been liked/skipped).")
        return

    with get_connection() as conn:
        for r in results:
            title, url = conn.execute(
                "SELECT title, url FROM items WHERE source = ? AND source_id = ?",
                (r["source"], r["source_id"]),
            ).fetchone()
            print(f"[{r['score']:.3f} | {r['basis']}] ({r['source']}) {title}")


if __name__ == "__main__":
    main()
