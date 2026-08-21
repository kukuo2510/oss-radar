"""Assign each item 1-3 semantic topic tags via zero-shot classification: cosine
similarity between the item's embedding and a small curated set of topic-label
embeddings. No training data or clustering needed - just define what topics matter
and embed them once.
"""

from datetime import datetime, timezone

import numpy as np

from db import get_all_embeddings, init_db, upsert_tags
from embed import load_model

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

TOP_K = 3
MIN_SCORE = 0.25


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main() -> None:
    init_db()
    embeddings = get_all_embeddings()
    if not embeddings:
        print("No embeddings found. Run embed.py first.")
        return

    print(f"Classifying {len(embeddings)} items into {len(TOPICS)} topics...")
    model = load_model()
    topic_names = list(TOPICS.keys())
    topic_vectors = list(model.embed(list(TOPICS.values())))

    created_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in embeddings:
        vec = np.frombuffer(item["vector"], dtype="float32")
        scores = [cosine_sim(vec, tv) for tv in topic_vectors]
        ranked = sorted(zip(topic_names, scores), key=lambda pair: pair[1], reverse=True)
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
