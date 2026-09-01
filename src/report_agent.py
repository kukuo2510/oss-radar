"""LLM narration layer for recommended items — mirrors the same pattern used by the
Vertex platform's other team (戶部/Stock): the quantitative pipeline (embed/classify/
trend/recommend) stays untouched and fully deterministic, this module only explains
*why* an already-computed recommendation was picked. It never re-scores or re-ranks
anything, so /recommendations and /trending stay reproducible and free to call.

Runs as its own pipeline step ("narrate"), not inline in the API request path — the
same reasoning as Vertex's report_agent.py: narrating live on every /recommendations
hit would mean an LLM call per item per request, which is both slow and pointlessly
expensive for data that doesn't change until the next daily pipeline run. Instead this
narrates the current top-N recommended candidates once per run and caches the result
in the `narrations` table; hydrate() in api.py reads from that cache.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from db import get_connection, get_narrations_map, init_db, upsert_narrations
from recommend import recommend

# 絕對路徑指到 oss-radar/.env（這個檔案在 src/ 底下，往上一層才是專案根目錄），不靠 cwd。
# 部署到 Render 時改用 Render 自己的環境變數面板設定，不需要這個檔案。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.environ.get("REPORT_AGENT_MODEL", "claude-sonnet-5")
TOP_N = 20  # narrate exactly what /recommendations would currently return at its default limit

SYSTEM_PROMPT = (
    "你是一個個人化推薦助理。你會拿到一筆已經算好的推薦項目"
    "（標題、描述、分類標籤、推薦分數、推薦依據），這些資訊不是你算的，你不能質疑或修改。"
    "請用 2 到 3 句繁體中文，寫一段簡短的推薦理由，說明這篇論文/專案/模型為什麼值得關注"
    "（引用給定的標題、描述、標籤內容），語氣像同事順手推薦的簡短點評。"
    "不要編造給定資訊以外的事實，也不要自己另外評分或排序。"
)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def narrate(item: dict) -> str:
    """item 需要至少有 title, description，其餘（category, tags, score, basis）可選。"""
    import json

    payload = {k: v for k, v in item.items() if v is not None}
    response = _client().messages.create(
        model=MODEL,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def main() -> None:
    init_db()
    candidates = recommend(top_n=TOP_N)
    if not candidates:
        print("No candidates to narrate (run recommend.py's prerequisites first).")
        return

    already = get_narrations_map()
    to_narrate = [c for c in candidates if (c["source"], c["source_id"]) not in already]
    if not to_narrate:
        print(f"All {len(candidates)} current top-{TOP_N} candidates already narrated, nothing to do.")
        return

    print(f"Narrating {len(to_narrate)} of {len(candidates)} candidates (rest already cached)...")
    rows = []
    with get_connection() as conn:
        for c in to_narrate:
            row = conn.execute(
                "SELECT title, description, category FROM items WHERE source = ? AND source_id = ?",
                (c["source"], c["source_id"]),
            ).fetchone()
            if not row:
                continue
            title, description, category = row
            tags = [t[0] for t in conn.execute(
                "SELECT tag FROM item_tags WHERE source = ? AND source_id = ? ORDER BY score DESC LIMIT 3",
                (c["source"], c["source_id"]),
            ).fetchall()]

            text = narrate({
                "title": title,
                "description": description,
                "category": category,
                "tags": tags,
                "score": round(c["score"], 3),
                "basis": c["basis"],
            })
            rows.append({
                "source": c["source"],
                "source_id": c["source_id"],
                "narration": text,
                "model": MODEL,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  ({c['source']}) {title[:50]}")

    upsert_narrations(rows)
    print(f"Narrated and cached {len(rows)} items.")


if __name__ == "__main__":
    main()
