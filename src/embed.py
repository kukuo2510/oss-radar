"""幫還沒有 embedding 的項目（跨所有資料來源）計算向量，寫回資料庫。

為什麼用 fastembed（底層是 ONNX runtime）而不是 sentence-transformers/torch：
這裡用的模型（BAAI/bge-small-en-v1.5，384 維）本身很小、只需要 CPU 就能跑，
不需要額外安裝或部署 GPU/torch 相依套件——這件事在正式環境是廉價主機或排程
工作、而不是開發機的時候特別重要。
"""

from datetime import datetime, timezone

from fastembed import TextEmbedding

from db import get_items_missing_embeddings, init_db, upsert_embeddings

MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 8

# 限制一次 main() 呼叫最多處理幾個項目。
# 在 CPU 被限制的主機上（Render 免費方案只有 0.15 vCPU），如果在同一個 HTTP 請求裡
# 把所有待處理項目一次 embed 完，很可能還沒 OOM 就先超過合理的請求逾時時間了。
# 每次呼叫設上限，代表呼叫端（管理端點，由 GitHub Actions 重複呼叫——詳見 README 的
# 「部署」章節）只要迴圈呼叫這支函式直到沒有剩餘項目即可，不需要單一請求扛下整批待處理量。
MAX_ITEMS_PER_RUN = 15

# 下面這幾個參數存在的唯一原因：512MB 記憶體的 Render 免費方案實例，用這個模型時一直 OOM。
# threads=1：限制 onnxruntime 的 intra-op 執行緒池大小（預設是每個 CPU 核心一條執行緒、
# 各自持有自己的緩衝區，這是第一個裝不下記憶體的元兇）。
# 停用 CPU memory arena：讓 onnxruntime 不要預先配置一塊可成長的記憶體池，
# 會犧牲一點單次呼叫的速度，但對一天只跑一次的背景工作來說完全可以接受。
# 這些調整在資源充足的開發機上完全不會被感覺到——它們只在正式環境資源吃緊時才有意義。
THREADS = 1
ORT_PROVIDERS = [
    ("CPUExecutionProvider", {"arena_extend_strategy": "kSameAsRequested", "enable_cpu_mem_arena": "0"})
]


def load_model() -> TextEmbedding:
    """依上面設定好的參數建立 embedding 模型實例。"""
    return TextEmbedding(model_name=MODEL_NAME, threads=THREADS, providers=ORT_PROVIDERS)


def build_text(item: dict) -> str:
    """把一個項目組合成單一字串餵給 embedding 模型：標題 + 描述。"""
    return f"{item['title']}. {item['description']}"


def main() -> int:
    """最多 embed MAX_ITEMS_PER_RUN 個項目。

    回傳值是這次呼叫結束後「還剩下多少個項目尚未 embed」，回傳 0 代表待處理清單已經清空。
    這個回傳值會被 api.py 的 /admin/run-step 端點用來告訴呼叫端（GitHub Actions）
    是否還需要再呼叫一次。
    """
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
