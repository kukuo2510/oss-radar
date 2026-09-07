"""抓取 HuggingFace Hub 上熱門的模型（models）與資料集（datasets），寫入 SQLite 資料庫。"""

from datetime import datetime, timezone

import requests

from db import init_db, upsert_items, record_snapshots

HF_ENDPOINTS = {
    "models": "https://huggingface.co/api/models",
    "datasets": "https://huggingface.co/api/datasets",
}


def fetch_hf(resource: str, max_results: int = 50) -> list[dict]:
    """依下載次數排序，抓取指定資源類型（models 或 datasets）中最熱門的項目。"""
    resp = requests.get(
        HF_ENDPOINTS[resource],
        params={"sort": "downloads", "direction": -1, "limit": max_results},
        timeout=30,
    )
    resp.raise_for_status()

    fetched_at = datetime.now(timezone.utc).isoformat()
    # models 的網址前綴跟 datasets 不同（datasets 網址多一段 /datasets/ 路徑）。
    base_url = "https://huggingface.co" if resource == "models" else "https://huggingface.co/datasets"

    items = []
    for entry in resp.json():
        entry_id = entry["id"]
        items.append(
            {
                # 用 huggingface_models / huggingface_datasets 區分兩種來源，
                # 避免同一個 id 在 models 和 datasets 之間互相覆蓋。
                "source": f"huggingface_{resource}",
                "source_id": entry_id,
                "title": entry_id,
                # 列表 API 沒有回傳完整的 model card 內容，目前先用 pipeline_tag
                # （例如 "text-generation"）當作簡略的描述文字，之後如果需要更完整的
                # 說明，得另外呼叫單一項目的詳細資料 API。
                "description": entry.get("pipeline_tag") or "",
                "url": f"{base_url}/{entry_id}",
                # HuggingFace 的 id 格式通常是 "作者/名稱"，取斜線前半段當作作者；
                # 沒有斜線（少數官方項目）就留空字串。
                "author": entry_id.split("/")[0] if "/" in entry_id else "",
                "category": entry.get("pipeline_tag") or "",
                "metric": entry.get("downloads") or 0,
                "published_at": entry.get("createdAt") or "",
                "fetched_at": fetched_at,
            }
        )
    return items


def main() -> None:
    """依序抓取 models 與 datasets 兩種資源，寫入項目資料並記錄下載數快照。"""
    init_db()
    total_new = 0
    for resource in HF_ENDPOINTS:
        items = fetch_hf(resource)
        new_count = upsert_items(items)
        record_snapshots(items)
        total_new += new_count
        print(f"[{resource}] fetched {len(items)}, {new_count} new")
    print(f"Done. {total_new} new HF entries stored.")


if __name__ == "__main__":
    main()
