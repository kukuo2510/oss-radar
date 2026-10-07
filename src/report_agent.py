"""給推薦項目加上 LLM 生成的解說文字 —— 沿用 Vertex 平台另一個團隊（戶部/Stock）
report_agent.py 的同一套模式：量化 pipeline（embed/classify/trend/recommend）
完全不受影響、維持全程可重現（deterministic），這個模組只負責解釋「為什麼」某個
已經算好的推薦項目會被選中。它從來不會重新計分或重新排序，所以 /recommendations
和 /trending 這兩個端點的結果依然是可重現、可以隨意呼叫的。

這個模組是獨立的一個 pipeline 步驟（"narrate"），而不是直接寫在 API 請求路徑裡 ——
理由跟 Vertex 的 report_agent.py 一樣：如果每次 /recommendations 被打到就即時生成解說，
代表每個請求都要對每個項目呼叫一次 LLM，既慢又沒必要地昂貴——反正這些資料在下一次
每日 pipeline 執行之前根本不會變。所以改成每次 pipeline 執行時，針對目前排名前 N 的
候選項目生成一次解說並快取進 `narrations` 資料表；api.py 的 hydrate() 就是從這個快取
裡讀取，而不是每次都重新生成。

LLM 來源可切換（REPORT_AGENT_PROVIDER）：預設 "ollama"，在使用者自己電腦上用本機模型
免費生成、直接寫進 Neon；"claude" 則呼叫付費的 Claude API（雲端 Render 上要用這個，
因為 Render 連不到使用者電腦上的 Ollama）。
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import opencc
import requests
from dotenv import load_dotenv

from db import get_connection, get_narrations_map, init_db, upsert_narrations
from recommend import recommend

# 絕對路徑指到 oss-radar/.env（這個檔案在 src/ 底下，往上一層才是專案根目錄），不靠 cwd。
# 部署到 Render 時改用 Render 自己的環境變數面板設定，不需要這個檔案。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROVIDER = os.environ.get("REPORT_AGENT_PROVIDER", "ollama")
DEFAULT_MODELS = {"ollama": "qwen2.5:14b", "claude": "claude-sonnet-5"}
MODEL = os.environ.get("REPORT_AGENT_MODEL", DEFAULT_MODELS[PROVIDER])
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# 本機模型（尤其 Qwen 系列）很容易混進簡體字或中國用語，輸出一律再過一次 OpenCC 的
# s2twp（簡體 → 繁體台灣用語，含詞彙轉換）。對本來就是繁體的文字不會有影響。
_TO_TAIWAN = opencc.OpenCC("s2twp")
TOP_N = 20  # 解說的候選項目數量，跟 /recommendations 端點目前預設回傳的筆數一致

SYSTEM_PROMPT = (
    "你是一個個人化推薦助理。你會拿到一筆已經算好的推薦項目"
    "（來源、標題、描述、推薦分數、推薦依據），這些資訊不是你算的，你不能質疑或修改。"
    "來源 source 決定它是什麼：arxiv 是論文、github 是開源專案、huggingface_models 是模型、"
    "huggingface_datasets 是資料集，稱呼要對。"
    "請用 2 到 3 句繁體中文，寫一段簡短的推薦理由，說明它為什麼值得關注"
    "（只根據給定的標題和描述），語氣像同事順手推薦的簡短點評。"
    "不要編造給定資訊以外的事實（例如從作者名稱猜程式語言、自行補充描述沒提到的功能），"
    "也不要自己另外評分或排序。"
    "請使用台灣用語，例如：透過（不是通過）、程式（不是程序）、執行（不是運行）、宣告式（不是聲明式）、"
    "強化學習（不是增強學習）、品質（不是質量）。"
)


def _client() -> anthropic.Anthropic:
    """建立 Anthropic API 用戶端；API key 透過標準的環境變數（ANTHROPIC_API_KEY）讀取。"""
    return anthropic.Anthropic()


def _narrate_ollama(content: str) -> str:
    """呼叫本機 Ollama 的 /api/chat（非串流）。temperature 調低，讓推薦理由貼著給定資訊寫、少發揮。"""
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "stream": False,
            # gpt-oss 這類推理模型的思考過程也算在 num_predict 裡，額度給太少會只有思考、沒有正文。
            **({"think": "low"} if MODEL.startswith("gpt-oss") else {}),
            "options": {"temperature": 0.3, "num_predict": 1024 if MODEL.startswith("gpt-oss") else 256},
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def narrate(item: dict) -> str:
    """item 需要至少有 title, description，其餘（source, score, basis）可選。

    把 item 內容整理成 JSON 傳給 LLM，請它依照 SYSTEM_PROMPT 的規則寫出一段簡短的
    推薦理由，只回傳文字內容（把回應裡的 text 區塊串接起來）。
    """
    import json

    # 只保留非 None 的欄位再送出，避免把一堆沒有意義的 null 塞進提示詞裡。
    payload = {k: v for k, v in item.items() if v is not None}
    content = json.dumps(payload, ensure_ascii=False, default=str)
    if PROVIDER == "ollama":
        return _TO_TAIWAN.convert(_narrate_ollama(content).strip())
    response = _client().messages.create(
        model=MODEL,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def main() -> None:
    """對目前排名前 TOP_N 的推薦候選項目生成解說文字，已經生成過的項目會直接略過（快取命中）。"""
    init_db()
    candidates = recommend(top_n=TOP_N)
    if not candidates:
        print("No candidates to narrate (run recommend.py's prerequisites first).")
        return

    # 只處理「目前候選清單裡、還沒有解說快取」的項目，避免每次執行都重複呼叫 LLM
    # 幫同樣的項目再生成一次一模一樣的內容，浪費 API 額度。
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
                "SELECT title, description FROM items WHERE source = %s AND source_id = %s",
                (c["source"], c["source_id"]),
            ).fetchone()
            if not row:
                continue
            title, description = row
            # 刻意不給分類標籤和 category：標籤是 zero-shot 自動猜的、常常不準，實測本機模型會把它
            # 當成事實寫進推薦理由（例如把沒提到的「機器人控制」寫成專案用途）。
            text = narrate({
                "source": c["source"],
                "title": title,
                "description": description,
                "score": round(c["score"], 3),
                "basis": c["basis"],
            })
            rows.append({
                "source": c["source"],
                "source_id": c["source_id"],
                "narration": text,
                "model": f"{PROVIDER}:{MODEL}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  ({c['source']}) {title[:50]}")

    upsert_narrations(rows)
    print(f"Narrated and cached {len(rows)} items.")


if __name__ == "__main__":
    main()
