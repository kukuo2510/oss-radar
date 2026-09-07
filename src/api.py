"""FastAPI 層，把整條資料 pipeline 的結果包裝成 HTTP API 給前端（PWA）使用。

為什麼需要這一層：這個 App 是瀏覽器/手機端的用戶端，沒辦法像 report.py 那樣直接
打開本機的 SQLite 檔案讀資料。專案裡其他腳本（ingest_*、embed、classify、trend、
recommend）已經把「真正的工作」做完了，這個模組只是把它們的執行結果和資料庫查詢
包裝成一組 HTTP 端點，讓前端可以透過網路存取。
"""

import gc
import os
from typing import Optional

import numpy as np
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastembed import TextEmbedding
from pydantic import BaseModel

import classify
import embed as embed_module
import ingest_arxiv
import ingest_github
import ingest_hf
import report_agent
import trend
from db import (
    get_all_embeddings,
    get_item,
    get_item_tags,
    get_items,
    get_narrations_map,
    get_tags_with_counts,
    get_top_trend_scores,
    init_db,
    record_interaction,
)
from embed import load_model
from recommend import cosine_sim, recommend as compute_recommendations

app = FastAPI(title="OSS Radar API")

# ALLOWED_ORIGINS 是逗號分隔的網域清單，例如 "https://oss-radar.vercel.app"。
# 預設值是 "*"，用於本機開發階段——這時候 PWA 真正上線的網域根本還不存在，
# 所以先全部放行，等正式部署再透過環境變數收斂成白名單。
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins_env == "*" else _allowed_origins_env.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 管理端點（/admin/run-step）用的驗證 token，從環境變數讀取；
# 沒設定的話就代表這個環境不允許透過 API 觸發 pipeline。
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

# 語意搜尋用的 embedding 模型是延遲載入（lazy load）的單例：
# 第一次呼叫 /search 時才真正建立，避免每次啟動 API 都要付出載入模型的成本。
_search_model: Optional[TextEmbedding] = None


def get_search_model() -> TextEmbedding:
    """回傳搜尋用的 embedding 模型；第一次呼叫時才真正建立並快取起來。"""
    global _search_model
    if _search_model is None:
        _search_model = load_model()
    return _search_model


@app.on_event("startup")
def on_startup() -> None:
    """API 啟動時先確保資料庫與資料表存在，避免第一個請求就因為資料表不存在而炸掉。"""
    init_db()


class InteractionIn(BaseModel):
    """使用者對某個項目按讚/略過時，前端送進來的請求內容。"""

    source: str
    source_id: str
    action: str  # "like" 或 "skip"


def hydrate(source: str, source_id: str, extra: dict | None = None) -> dict | None:
    """把資料庫裡的單一項目補上標籤（tags），必要時再併入額外欄位（例如分數、推薦理由）。

    這個函式被 /trending、/recommendations、/search 共用，
    是因為這三個端點都需要「先拿到項目基本資料，再補上 tags 和各自的分數/理由」這個相同的流程。
    """
    item = get_item(source, source_id)
    if not item:
        return None
    item["tags"] = get_item_tags(source, source_id)
    if extra:
        item.update(extra)
    return item


@app.get("/items")
def list_items(
    source: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
):
    """依來源（source）/標籤（tag）分頁列出項目清單，每筆都會補上 tags。"""
    items = get_items(source=source, tag=tag, limit=limit, offset=offset)
    for item in items:
        item["tags"] = get_item_tags(item["source"], item["source_id"])
    return items


@app.get("/items/{source}/{source_id:path}")
def item_detail(source: str, source_id: str):
    """取得單一項目的完整資料；查無此項目回傳 404。"""
    item = hydrate(source, source_id)
    if not item:
        raise HTTPException(404, "item not found")
    return item


@app.get("/tags")
def list_tags():
    """列出所有標籤與各自出現的次數，給前端做篩選用的標籤雲。"""
    return get_tags_with_counts()


@app.get("/trending")
def trending(limit: int = Query(20, le=100)):
    """取得目前熱門排行榜，附上每個項目的分數、判斷依據（basis）與 LLM 生成的解說文字。"""
    rows = get_top_trend_scores(limit=limit)
    narrations = get_narrations_map()
    results = [
        hydrate(r["source"], r["source_id"], {
            "score": r["score"], "basis": r["basis"],
            "narration": narrations.get((r["source"], r["source_id"])),
        })
        for r in rows
    ]
    # hydrate() 在項目已被刪除等情況下可能回傳 None，這裡把這些空值濾掉，
    # 避免回傳給前端的清單裡混雜 null。
    return [r for r in results if r]


@app.get("/recommendations")
def recommendations(limit: int = Query(20, le=100)):
    """依照使用者過去的按讚/略過紀錄，計算個人化推薦清單。"""
    rows = compute_recommendations(top_n=limit)
    narrations = get_narrations_map()
    results = [
        hydrate(r["source"], r["source_id"], {
            "score": r["score"], "basis": r["basis"],
            "narration": narrations.get((r["source"], r["source_id"])),
        })
        for r in rows
    ]
    return [r for r in results if r]


@app.get("/search")
def search(q: str, limit: int = Query(20, le=100)):
    """語意搜尋：把查詢字串轉成向量，跟資料庫裡所有項目的向量算 cosine 相似度後排序。

    目前是把全部 embedding 讀進記憶體逐一比對（線性掃描），
    在項目數量還不大的情況下夠用；之後如果資料量變大，
    才需要考慮换成向量資料庫或近似最近鄰（ANN）索引。
    """
    if not q.strip():
        raise HTTPException(400, "q must not be empty")

    model = get_search_model()
    query_vector = next(model.embed([q]))

    scored = []
    for row in get_all_embeddings():
        vec = np.frombuffer(row["vector"], dtype="float32")
        scored.append((row["source"], row["source_id"], cosine_sim(query_vector, vec)))
    scored.sort(key=lambda t: t[2], reverse=True)

    results = [hydrate(source, source_id, {"score": score}) for source, source_id, score in scored[:limit]]
    return [r for r in results if r]


@app.post("/interactions")
def create_interaction(payload: InteractionIn):
    """記錄使用者的按讚/略過行為，作為之後 /recommendations 計算推薦分數的依據。"""
    if payload.action not in ("like", "skip"):
        raise HTTPException(400, "action must be 'like' or 'skip'")
    record_interaction(payload.source, payload.source_id, payload.action)
    return {"status": "ok"}


# 管理端點可以觸發的 pipeline 步驟對照表：
# key 是 API 路徑裡的 step 名稱，value 是實際要呼叫的函式。
PIPELINE_STEPS = {
    "arxiv": ingest_arxiv.main,
    "github": ingest_github.main,
    "huggingface": ingest_hf.main,
    "embed": embed_module.main,
    "classify": classify.main,
    "trend": trend.main,
    "narrate": report_agent.main,
}


@app.post("/admin/run-step/{step}")
def run_step(step: str, x_admin_token: Optional[str] = Header(default=None)):
    """執行單一個 pipeline 步驟並回傳結果。

    為什麼一次只跑一個步驟：免費方案的主機（Render 等）通常沒有內建排程（cron）功能，
    目前的作法是改用外部免費排程器（一個 GitHub Actions workflow）每天呼叫這個端點一次、
    一次一個步驟，取代 scheduler.py 在本機用 APScheduler 常駐排程的做法。

    「一次一個步驟」是刻意的設計，不只是為了簡化邏輯：曾經在同一個請求裡把 6 個步驟
    全部串起來執行，結果把 512MB 記憶體的 Render 免費方案實例跑到 OOM——因為 embed 和
    classify 各自都會載入一份 embedding 模型，而同一個請求內，直譯器沒有機會在步驟之間
    釋放記憶體。拆成各自獨立的請求，可以把尖峰記憶體用量限制在單一步驟所需的範圍內，
    下面的 gc.collect() 則是額外提醒直譯器盡快釋放記憶體，讓下一個請求進來時環境是乾淨的。
    """
    if not ADMIN_TOKEN:
        raise HTTPException(503, "admin pipeline not configured (ADMIN_TOKEN unset)")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "invalid admin token")
    if step not in PIPELINE_STEPS:
        raise HTTPException(404, f"unknown step {step!r}, expected one of {list(PIPELINE_STEPS)}")

    try:
        result = PIPELINE_STEPS[step]()
    except Exception as e:
        raise HTTPException(500, f"{step} failed: {e}")
    finally:
        gc.collect()

    response = {"step": step, "status": "ok"}
    if result is not None:  # 目前只有 embed 步驟會回傳這個：還有多少項目待處理
        response["remaining"] = result
    return response
