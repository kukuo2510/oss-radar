"""Compute embeddings for items that don't have one yet, across all sources.

Using fastembed (ONNX runtime) instead of sentence-transformers/torch: the model
(BAAI/bge-small-en-v1.5, 384-dim) is small, CPU-only, and has no GPU/torch dependency
to install or ship, which matters once this runs on a cheap deploy box or inside a
scheduled job rather than a dev machine.
"""

from datetime import datetime, timezone

from fastembed import TextEmbedding

from db import get_items_missing_embeddings, init_db, upsert_embeddings

MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 64


def build_text(item: dict) -> str:
    return f"{item['title']}. {item['description']}"


def main() -> None:
    init_db()
    items = get_items_missing_embeddings()
    if not items:
        print("No items need embeddings.")
        return

    print(f"Embedding {len(items)} items with {MODEL_NAME}...")
    model = TextEmbedding(model_name=MODEL_NAME)
    texts = [build_text(item) for item in items]
    created_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for item, vector in zip(items, model.embed(texts, batch_size=BATCH_SIZE)):
        rows.append(
            {
                "source": item["source"],
                "source_id": item["source_id"],
                "model": MODEL_NAME,
                "vector": vector.astype("float32").tobytes(),
                "dim": vector.shape[0],
                "created_at": created_at,
            }
        )

    upsert_embeddings(rows)
    print(f"Stored {len(rows)} embeddings.")


if __name__ == "__main__":
    main()
