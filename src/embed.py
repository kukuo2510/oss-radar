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
BATCH_SIZE = 8
# Caps how many items one main() call embeds. On a CPU-throttled host (Render free
# is 0.15 vCPU) embedding everything in one HTTP request can run past any
# reasonable request timeout well before it OOMs. Bounding it per call means the
# caller (the admin endpoint, called repeatedly by GitHub Actions - see README's
# "部署" section) just calls this in a loop until nothing's left, instead of one
# request having to finish the whole backlog.
MAX_ITEMS_PER_RUN = 15
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


def main() -> int:
    """Embeds up to MAX_ITEMS_PER_RUN items. Returns how many are still left
    unembedded afterward (0 means the backlog is fully drained)."""
    init_db()
    all_missing = get_items_missing_embeddings()
    if not all_missing:
        print("No items need embeddings.")
        return 0

    items = all_missing[:MAX_ITEMS_PER_RUN]
    print(f"Embedding {len(items)} of {len(all_missing)} pending items with {MODEL_NAME}...")
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
    remaining = len(all_missing) - len(rows)
    print(f"Stored {len(rows)} embeddings. {remaining} still pending.")
    return remaining


if __name__ == "__main__":
    main()
