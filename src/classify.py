"""用零樣本分類（zero-shot classification）幫每個項目標上 1~3 個語意主題標籤。

做法是拿項目的 embedding，跟一小組手工挑選好的主題標籤 embedding 算 cosine 相似度，
分數最高的幾個就當作這個項目的標籤。這種做法不需要訓練資料、也不用做分群（clustering），
只要先定義好「有哪些主題值得關注」，把這些主題描述文字 embed 一次即可，之後每次分類
都直接重複使用同一組主題向量。
"""

from datetime import datetime, timezone

import numpy as np

from db import get_all_embeddings, init_db, upsert_tags
from embed import load_model

# 主題名稱 -> 該主題的描述文字（會被 embed 成向量，用來跟項目向量比對相似度）。
# 描述文字刻意寫得比較長、涵蓋多個同義詞/相關詞，是為了讓 embedding 更能代表整個主題的語意範圍，
# 而不是只匹配到單一關鍵字。
TOPICS = {
    "Large Language Models": "large language models, LLMs, transformers, prompting, fine-tuning, instruction tuning",
    "AI Agents & Tool Use": "autonomous agents, tool use, multi-agent systems, agentic workflows, planning",
    "Retrieval & Search": "retrieval augmented generation, RAG, vector search, semantic search, information retrieval",
    "Computer Vision": "image recognition, object detection, image generation, diffusion models, vision transformers",
    "Multimodal": "multimodal models combining vision, text, audio, video understanding",
    "Speech & Audio": "speech recognition, text-to-speech, audio processing, voice models",
    "Reinforcement Learning": "reinforcement learning, reward modeling, policy optimization, RLHF",
    "Robotics & Control": "robotics, control systems, embodied AI, simulation, manipulation",
    "Recommender Systems": "recommendation systems, personalization, ranking, collaborative filtering",
    "MLOps & Infrastructure": "model deployment, serving infrastructure, ML pipelines, monitoring, scaling, efficient inference",
    "Data & Evaluation": "datasets, data collection, benchmarks, evaluation, AI safety, alignment, bias and fairness",
}

# 每個項目最多保留幾個標籤、以及標籤能被採用的最低相似度門檻。
TOP_K = 3
MIN_SCORE = 0.25


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """計算兩個向量的 cosine 相似度（範圍約在 -1 ~ 1，愈接近 1 代表語意愈相近）。"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main() -> None:
    """讀出所有項目的 embedding，逐一跟主題向量比對，把符合門檻的標籤寫回資料庫。"""
    init_db()
    embeddings = get_all_embeddings()
    if not embeddings:
        print("No embeddings found. Run embed.py first.")
        return

    print(f"Classifying {len(embeddings)} items into {len(TOPICS)} topics...")
    model = load_model()
    topic_names = list(TOPICS.keys())
    # 主題向量只需要在整個分類流程開始前算一次，之後對每個項目重複使用，
    # 避免對同樣 11 個主題描述重複呼叫模型。
    topic_vectors = list(model.embed(list(TOPICS.values())))

    created_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in embeddings:
        vec = np.frombuffer(item["vector"], dtype="float32")
        scores = [cosine_sim(vec, tv) for tv in topic_vectors]
        ranked = sorted(zip(topic_names, scores), key=lambda pair: pair[1], reverse=True)
        # 篩選規則：先取分數最高的 TOP_K 個裡面，分數有達到 MIN_SCORE 門檻的；
        # 如果一個都沒有達標（`or` 後半段），退而求其次至少保留分數最高的那一個標籤，
        # 避免有項目完全沒有任何標籤可用。
        top = [pair for pair in ranked[:TOP_K] if pair[1] >= MIN_SCORE] or ranked[:1]
        for tag, score in top:
            rows.append(
                {
                    "source": item["source"],
                    "source_id": item["source_id"],
                    "tag": tag,
                    "score": score,
                    "created_at": created_at,
                }
            )

    upsert_tags(rows)
    print(f"Stored {len(rows)} tag assignments across {len(embeddings)} items.")


if __name__ == "__main__":
    main()
