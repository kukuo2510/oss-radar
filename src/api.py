"""FastAPI layer exposing the pipeline's data to a future client (the PWA).

This exists because the app is a browser/mobile client - it can't open the SQLite
file directly the way report.py does. Every other script in this project (ingest_*,
embed, classify, trend, recommend) already does the real work; this module just
wraps their outputs and DB reads as HTTP endpoints.
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
import trend
from db import (
    get_all_embeddings,
    get_item,
    get_item_tags,
    get_items,
    get_tags_with_counts,
    get_top_trend_scores,
    init_db,
    record_interaction,
)
from embed import MODEL_NAME, THREADS
from recommend import cosine_sim, recommend as compute_recommendations

app = FastAPI(title="OSS Radar API")

# ALLOWED_ORIGINS is a comma-separated list, e.g. "https://oss-radar.vercel.app".
# Defaults to "*" for local dev, where the PWA's real origin doesn't exist yet.
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins_env == "*" else _allowed_origins_env.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

_search_model: Optional[TextEmbedding] = None


def get_search_model() -> TextEmbedding:
    global _search_model
    if _search_model is None:
        _search_model = TextEmbedding(model_name=MODEL_NAME, threads=THREADS)
    return _search_model


@app.on_event("startup")
def on_startup() -> None:
    init_db()


class InteractionIn(BaseModel):
    source: str
    source_id: str
    action: str  # "like" or "skip"


def hydrate(source: str, source_id: str, extra: dict | None = None) -> dict | None:
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
    items = get_items(source=source, tag=tag, limit=limit, offset=offset)
    for item in items:
        item["tags"] = get_item_tags(item["source"], item["source_id"])
    return items


@app.get("/items/{source}/{source_id:path}")
def item_detail(source: str, source_id: str):
    item = hydrate(source, source_id)
    if not item:
        raise HTTPException(404, "item not found")
    return item


@app.get("/tags")
def list_tags():
    return get_tags_with_counts()


@app.get("/trending")
def trending(limit: int = Query(20, le=100)):
    rows = get_top_trend_scores(limit=limit)
    results = [hydrate(r["source"], r["source_id"], {"score": r["score"], "basis": r["basis"]}) for r in rows]
    return [r for r in results if r]


@app.get("/recommendations")
def recommendations(limit: int = Query(20, le=100)):
    rows = compute_recommendations(top_n=limit)
    results = [hydrate(r["source"], r["source_id"], {"score": r["score"], "basis": r["basis"]}) for r in rows]
    return [r for r in results if r]


@app.get("/search")
def search(q: str, limit: int = Query(20, le=100)):
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
    if payload.action not in ("like", "skip"):
        raise HTTPException(400, "action must be 'like' or 'skip'")
    record_interaction(payload.source, payload.source_id, payload.action)
    return {"status": "ok"}


PIPELINE_STEPS = {
    "arxiv": ingest_arxiv.main,
    "github": ingest_github.main,
    "huggingface": ingest_hf.main,
    "embed": embed_module.main,
    "classify": classify.main,
    "trend": trend.main,
}


@app.post("/admin/run-step/{step}")
def run_step(step: str, x_admin_token: Optional[str] = Header(default=None)):
    """Runs exactly one pipeline step and returns. This exists because free-tier
    hosting (Render, etc.) doesn't include a cron feature - the plan is an external
    free scheduler (a GitHub Actions workflow) calling this once per step, once a
    day, instead of running an in-process APScheduler like scheduler.py does locally.

    One step per request is deliberate, not just for simplicity: running all 6 steps
    back-to-back inside a single request OOM'd a 512MB Render free instance (embed
    and classify each load their own copy of the embedding model, and the process
    never got a chance to release memory between steps within one request). Splitting
    into separate requests bounds peak memory to whatever a single step needs, and
    gc.collect() below gives the interpreter an extra nudge to release it before the
    next request comes in."""
    if not ADMIN_TOKEN:
        raise HTTPException(503, "admin pipeline not configured (ADMIN_TOKEN unset)")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "invalid admin token")
    if step not in PIPELINE_STEPS:
        raise HTTPException(404, f"unknown step {step!r}, expected one of {list(PIPELINE_STEPS)}")

    try:
        PIPELINE_STEPS[step]()
    except Exception as e:
        raise HTTPException(500, f"{step} failed: {e}")
    finally:
        gc.collect()
    return {"step": step, "status": "ok"}
