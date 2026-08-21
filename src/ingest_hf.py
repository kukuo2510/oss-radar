"""Fetch popular models and datasets from the HuggingFace Hub and store them in SQLite."""

from datetime import datetime, timezone

import requests

from db import init_db, upsert_items, record_snapshots

HF_ENDPOINTS = {
    "models": "https://huggingface.co/api/models",
    "datasets": "https://huggingface.co/api/datasets",
}


def fetch_hf(resource: str, max_results: int = 50) -> list[dict]:
    resp = requests.get(
        HF_ENDPOINTS[resource],
        params={"sort": "downloads", "direction": -1, "limit": max_results},
        timeout=30,
    )
    resp.raise_for_status()

    fetched_at = datetime.now(timezone.utc).isoformat()
    base_url = "https://huggingface.co" if resource == "models" else "https://huggingface.co/datasets"

    items = []
    for entry in resp.json():
        entry_id = entry["id"]
        items.append(
            {
                "source": f"huggingface_{resource}",
                "source_id": entry_id,
                "title": entry_id,
                # The listing endpoint doesn't include the full model card text,
                # only pipeline_tag as a rough description for now.
                "description": entry.get("pipeline_tag") or "",
                "url": f"{base_url}/{entry_id}",
                "author": entry_id.split("/")[0] if "/" in entry_id else "",
                "category": entry.get("pipeline_tag") or "",
                "metric": entry.get("downloads") or 0,
                "published_at": entry.get("createdAt") or "",
                "fetched_at": fetched_at,
            }
        )
    return items


def main() -> None:
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
