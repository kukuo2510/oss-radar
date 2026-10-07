"""FastAPI 層，把整條資料 pipeline 的結果包裝成 HTTP API 給前端（PWA）使用。

為什麼需要這一層：這個 App 是瀏覽器/手機端的用戶端，沒辦法像 report.py 那樣直接
打開本機的 SQLite 檔案讀資料。專案裡其他腳本（ingest_*、embed、classify、trend、
recommend）已經把「真正的工作」做完了，這個模組只是把它們的執行結果和資料庫查詢
包裝成一組 HTTP 端點，讓前端可以透過網路存取。
"""

import gc
import os
from datetime import datetime, timezone
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
import reader_fetch
import report_agent
import trend
from db import (
    add_reading_item,
    count_pending_reading_items,
    delete_reading_item,
    get_reading_item,
    get_worker_status,
    list_reading_items,
    update_reading_item,
    get_all_embeddings,
    get_item,
    get_item_tags,
    get_items,
    get_items_by_keys,
    get_narrations_map,
    get_tags_for_keys,
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


def hydrate_many(rows: list[tuple[str, str, dict]]) -> list[dict]:
    """hydrate() 的批次版：(source, source_id, extra) 清單一次查完項目與標籤，保留原本順序，
    已不存在的項目直接略過。清單型端點都用這個——資料庫在 Neon 上，逐筆查詢的網路往返
    會讓一頁 20 筆的推薦要等 20 秒以上。"""
    keys = [(source, source_id) for source, source_id, _ in rows]
    items = get_items_by_keys(keys)
    tags = get_tags_for_keys(keys)
    results = []
    for source, source_id, extra in rows:
        item = items.get((source, source_id))
        if not item:
            continue
        item["tags"] = tags.get((source, source_id), [])
        item.update(extra)
        results.append(item)
    return results


@app.get("/items")
def list_items(
    source: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
):
    """依來源（source）/標籤（tag）分頁列出項目清單，每筆都會補上 tags。"""
    items = get_items(source=source, tag=tag, limit=limit, offset=offset)
    tags = get_tags_for_keys([(item["source"], item["source_id"]) for item in items])
    for item in items:
        item["tags"] = tags.get((item["source"], item["source_id"]), [])
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
    return hydrate_many([
        (r["source"], r["source_id"], {
            "score": r["score"], "basis": r["basis"],
            "narration": narrations.get((r["source"], r["source_id"])),
        })
        for r in rows
    ])


@app.get("/recommendations")
def recommendations(limit: int = Query(20, le=100)):
    """依照使用者過去的按讚/略過紀錄，計算個人化推薦清單。"""
    rows = compute_recommendations(top_n=limit)
    narrations = get_narrations_map()
    return hydrate_many([
        (r["source"], r["source_id"], {
            "score": r["score"], "basis": r["basis"],
            "narration": narrations.get((r["source"], r["source_id"])),
        })
        for r in rows
    ])


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

    return hydrate_many([(source, source_id, {"score": score}) for source, source_id, score in scored[:limit]])


@app.post("/interactions")
def create_interaction(payload: InteractionIn):
    """記錄使用者的按讚/略過行為，作為之後 /recommendations 計算推薦分數的依據。"""
    if payload.action not in ("like", "skip"):
        raise HTTPException(400, "action must be 'like' or 'skip'")
    record_interaction(payload.source, payload.source_id, payload.action)
    return {"status": "ok"}


# ---------------------------------------------------------------- 深讀
# API 只負責收連結、提供清單與閱讀內容；抓取和翻譯由使用者電腦上的 reader_worker.py 做。

MAX_PENDING_READING = 30  # 佇列上限：API 沒有登入機制，避免被大量塞連結時本機 worker 一直翻
WORKER_ONLINE_SECONDS = 2 * 3600  # 心跳在這段時間內，前端就顯示「翻譯站在線」


class ReadingIn(BaseModel):
    """可以直接是網址，也可以是手機分享時帶來的一整段文字（裡面含網址）。"""

    url: str


class ReadingPatch(BaseModel):
    read_progress: float


def normalize_reading_url(raw: str) -> str:
    """從分享文字中找出支援的連結並正規化（去掉 ?s=20 這類追蹤參數），同一篇不會重複加入。"""
    m = reader_fetch.X_STATUS_RE.search(raw)
    if m:
        return f"https://x.com/{m.group(1) or 'i'}/status/{m.group(2)}"
    if "arxiv.org" in raw or reader_fetch.ARXIV_ID_RE.fullmatch(raw.strip()):
        m = reader_fetch.ARXIV_ID_RE.search(raw)
        if m:
            return f"https://arxiv.org/abs/{m.group(1)}"
    raise HTTPException(400, "目前只支援 X（x.com／twitter.com）貼文與 arXiv 論文連結")


@app.post("/reading")
def add_reading(payload: ReadingIn):
    url = normalize_reading_url(payload.url)
    if count_pending_reading_items() >= MAX_PENDING_READING:
        raise HTTPException(429, "待處理的文章太多了，等翻譯站消化一些再加")
    return add_reading_item(url)


@app.get("/reading")
def reading_list():
    return list_reading_items()


@app.get("/reading/worker")
def reading_worker_status():
    """翻譯站（使用者電腦上的 worker）最後一次回報的時間與模型。"""
    status = get_worker_status()
    if not status:
        return {"online": False, "last_seen": None, "model": None}
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(status["last_seen"])).total_seconds()
    return {"online": age < WORKER_ONLINE_SECONDS, **status}


@app.get("/reading/{item_id}")
def reading_detail(item_id: int):
    item = get_reading_item(item_id, with_content=True)
    if not item:
        raise HTTPException(404, "reading item not found")
    return item


@app.patch("/reading/{item_id}")
def update_reading(item_id: int, payload: ReadingPatch):
    if not get_reading_item(item_id):
        raise HTTPException(404, "reading item not found")
    update_reading_item(item_id, read_progress=min(max(payload.read_progress, 0.0), 1.0))
    return {"status": "ok"}


@app.post("/reading/{item_id}/retry")
def retry_reading(item_id: int):
    item = get_reading_item(item_id)
    if not item:
        raise HTTPException(404, "reading item not found")
    if item["status"] != "failed":
        raise HTTPException(409, "只有失敗的項目可以重試")
    update_reading_item(item_id, status="queued", error=None)
    return {"status": "ok"}


@app.delete("/reading/{item_id}")
def remove_reading(item_id: int):
    if not delete_reading_item(item_id):
        raise HTTPException(404, "reading item not found")
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
