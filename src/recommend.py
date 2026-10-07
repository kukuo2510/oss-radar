"""以內容為基礎（content-based）的個人化排序。

作法：把所有按讚項目的 embedding 平均起來，組成一個「使用者輪廓向量」（user profile），
並讓略過過的項目的 embedding 稍微把這個輪廓向量往反方向拉一點；接著對所有還沒看過的
項目，依照跟這個輪廓向量的 cosine 相似度排序。最終排序會把這個「個人化訊號」跟
trend.py 算出來的熱度分數加權混合，讓「符合喜好、而且目前正在熱門」的項目排在
「符合喜好、但已經是舊聞」的項目之前。

冷啟動（cold start）：如果完全沒有互動紀錄，就沒有輪廓向量可以建立，這時候排序
會退回單純用熱度分數排序——這跟 trend.py 本身處理全新項目時用的冷啟動邏輯是同一套模式。
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

# 最終分數 = 個人化分數 * PERSONALIZATION_WEIGHT + 熱度分數 * TREND_WEIGHT。
PERSONALIZATION_WEIGHT = 0.6
TREND_WEIGHT = 0.4

# 略過（skip）的項目要把輪廓向量往反方向拉多少，相對於「按讚會把輪廓向量拉近多少」的比例。
# 0.3 代表「略過」的影響力只有「按讚」的三成，是刻意調弱的——避免使用者少數幾次誤觸略過，
# 就大幅扭曲整個推薦輪廓。
SKIP_PENALTY = 0.3


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """計算兩個向量的 cosine 相似度。"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def build_user_profile(embeddings_by_key: dict, interactions: dict) -> np.ndarray | None:
    """依使用者的按讚/略過紀錄，組出代表其偏好的「輪廓向量」。

    沒有任何按讚紀錄時回傳 None，代表目前無法建立個人化輪廓（冷啟動情境）。
    """
    liked = [
        embeddings_by_key[key]
        for key, action in interactions.items()
        if action == "like" and key in embeddings_by_key
    ]
    skipped = [
        embeddings_by_key[key]
        for key, action in interactions.items()
        if action == "skip" and key in embeddings_by_key
    ]

    if not liked:
        return None

    profile = np.mean(liked, axis=0)
    if skipped:
        profile = profile - SKIP_PENALTY * np.mean(skipped, axis=0)
    return profile


def recommend(top_n: int = 20) -> list[dict]:
    """計算個人化推薦清單；沒有足夠的按讚資料時，自動退回純熱度排序。"""
    embeddings_by_key = {
        (row["source"], row["source_id"]): np.frombuffer(row["vector"], dtype="float32")
        for row in get_all_embeddings()
    }
    interactions = get_latest_interactions()
    trend_scores = get_all_trend_scores()

    # 候選清單只保留「還沒有任何互動紀錄（沒按讚也沒略過）」的項目，
    # 已經表態過的項目沒有必要再推薦一次。
    candidates = {key: vec for key, vec in embeddings_by_key.items() if key not in interactions}
    if not candidates:
        return []

    profile = build_user_profile(embeddings_by_key, interactions)

    if profile is None:
        # 冷啟動：完全沒有按讚紀錄，退回單純依熱度分數排序。
        ranked = sorted(candidates, key=lambda k: trend_scores.get(k, 0.0), reverse=True)[:top_n]
        return [
            {"source": k[0], "source_id": k[1], "score": trend_scores.get(k, 0.0), "basis": "trend_only"}
            for k in ranked
        ]

    # 個人化分數與熱度分數的量級可能天差地遠（cosine 相似度落在 -1~1，熱度分數的範圍
    # 則取決於原始指標），所以先各自轉成百分位排名（0~1）再加權混合，確保兩個訊號
    # 的影響力是照 PERSONALIZATION_WEIGHT / TREND_WEIGHT 的比例分配，而不是被其中一個
    # 天生數值範圍較大的訊號主導。
    personalization_ranks = percentile_ranks({key: cosine_sim(vec, profile) for key, vec in candidates.items()})
    trend_ranks = percentile_ranks({key: trend_scores.get(key, 0.0) for key in candidates})

    combined = {
        key: PERSONALIZATION_WEIGHT * personalization_ranks[key] + TREND_WEIGHT * trend_ranks[key]
        for key in candidates
    }
    ranked = sorted(combined, key=lambda k: combined[k], reverse=True)[:top_n]
    return [{"source": k[0], "source_id": k[1], "score": combined[k], "basis": "personalized"} for k in ranked]


def main() -> None:
    """計算推薦清單並印出結果（附上分數與判斷依據），方便在命令列快速檢視效果。"""
    init_db()
    results = recommend()
    if not results:
        print("No candidates to recommend (run embed.py first, and make sure not everything has been liked/skipped).")
        return

    with get_connection() as conn:
        for r in results:
            title, url = conn.execute(
                "SELECT title, url FROM items WHERE source = %s AND source_id = %s",
                (r["source"], r["source_id"]),
            ).fetchone()
            print(f"[{r['score']:.3f} | {r['basis']}] ({r['source']}) {title}")


if __name__ == "__main__":
    main()
