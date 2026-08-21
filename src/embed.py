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
BATCH_SIZE = 1
# Every knob here exists for one reason: a 512MB Render free instance kept OOM-ing
# on this model. threads=1 caps onnxruntime's intra-op thread pool (its default -
# one thread per CPU core, each with its own buffers - was the first thing that
# didn't fit). Disabling the CPU memory arena stops onnxruntime from pre-allocating
# a growable memory pool up front; it costs a bit of speed per call, which a
# background job running once a day can afford. None of this matters on a dev
# machine with RAM to spare - it only matters because production doesn't have it.
THREADS = 1
ORT_PROVIDERS = [
    ("CPUExecutionProvider", {"arena_extend_strategy": "kSameAsRequested", "enable_cpu_mem_arena": "0"})
]


def load_model() -> TextEmbedding:
    return TextEmbedding(model_name=MODEL_NAME, threads=THREADS, providers=ORT_PROVIDERS)


def build_text(item: dict) -> str:
    return f"{item['title']}. {item['description']}"


def main() -> None:
    init_db()
    items = get_items_missing_embeddings()
    if not items:
        print("No items need embeddings.")
        return

    print(f"Embedding {len(items)} items with {MODEL_NAME}...")
    model = load_model()
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
