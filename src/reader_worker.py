"""深讀功能的本機 worker：在使用者自己的電腦上跑（要用本機 Ollama 翻譯）。

每次執行做三件事：
1. 回報心跳（閱讀頁顯示「翻譯站已連線」靠這個）。
2. 把佇列裡的連結一筆一筆抓下來、翻譯，進度與結果寫回 Neon。
   上次被中斷（電腦關機）的項目會放回佇列，已翻好的段落沿用，不會重翻。
3. 佇列清空後，順便用本機 Ollama 補寫推薦理由（report_agent.py）。

不常駐輪詢：Neon 免費方案閒置才會休眠，用 Windows 工作排程器定時執行一次即可。

用法（在 src/ 底下）：
    python reader_worker.py              # 處理完佇列就結束
    python reader_worker.py --no-narrate # 不補寫推薦理由
"""

import argparse
import msvcrt
import sys
import time
import traceback
from pathlib import Path

import db
import reader_fetch
import reader_translate
import report_agent

# 翻譯進度不需要每段都寫資料庫：每 5 段或至少間隔 20 秒存一次，最後一段一定存。
SAVE_EVERY_BLOCKS = 5
SAVE_EVERY_SECONDS = 20


def process(item: dict, model: str) -> None:
    item_id = item["id"]
    print(f"\n=== #{item_id} {item['url']}", flush=True)

    doc, prev = db.get_reading_doc(item_id)
    if doc is None:
        doc = reader_fetch.fetch(item["url"])
        db.save_reading_doc(item_id, doc)
    total = sum(1 for b in doc["blocks"] if b["translate"])
    db.update_reading_item(
        item_id,
        source=doc["source"],
        source_id=doc["source_id"],
        title=doc.get("title"),
        authors=doc.get("authors"),
        published_at=doc.get("published_at"),
        extraction=doc.get("extraction"),
        warnings=doc.get("warnings"),
        status="translating",
        progress_total=total,
    )

    last_save = {"t": 0.0}

    def on_progress(result: dict, done: int, total_: int) -> None:
        if done == total_ or done % SAVE_EVERY_BLOCKS == 0 or time.time() - last_save["t"] > SAVE_EVERY_SECONDS:
            db.save_reading_translation(item_id, result)
            db.update_reading_item(item_id, progress_done=done, title_zh=result.get("title_zh"))
            last_save["t"] = time.time()

    result = reader_translate.translate(doc, model, prev, on_progress=on_progress, name=f"reading#{item_id}")
    db.save_reading_translation(item_id, result)
    s = result["stats"]
    db.update_reading_item(item_id, status="ready", progress_done=total, title_zh=result.get("title_zh"))
    print(f"完成：{s['ok']}/{s['blocks']} 段通過檢查，{s['fallback']} 段保留原文", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=reader_translate.DEFAULT_MODEL)
    ap.add_argument("--no-narrate", action="store_true", help="不補寫推薦理由")
    args = ap.parse_args()

    # 同一台電腦同時只跑一個 worker：排程剛好在手動執行時觸發的話，兩個會搶同一篇、
    # 還會把對方正在翻的項目當成「中斷」放回佇列。用檔案鎖擋掉第二個。
    lock_path = Path(__file__).resolve().parent.parent / "data" / "reader" / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "a+")
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("另一個翻譯站正在執行，這次跳過", flush=True)
        return 0

    db.init_db()
    db.worker_heartbeat(args.model)
    resumed = db.requeue_interrupted_reading_items()
    if resumed:
        print(f"{resumed} 筆上次中斷的項目放回佇列", flush=True)

    handled = 0
    while (item := db.claim_next_reading_item()) is not None:
        try:
            process(item, args.model)
        except Exception as e:  # 單篇失敗不影響後面的項目
            traceback.print_exc()
            db.update_reading_item(item["id"], status="failed", error=f"{type(e).__name__}: {e}"[:500])
        handled += 1
        db.worker_heartbeat(args.model)
    print(f"\n佇列處理完畢，本次處理 {handled} 筆", flush=True)

    if not args.no_narrate:
        try:
            report_agent.main()
        except Exception:
            traceback.print_exc()
    db.worker_heartbeat(args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
