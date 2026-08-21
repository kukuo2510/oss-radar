"""FastAPI layer exposing the pipeline's data to a future client (the PWA).

This exists because the app is a browser/mobile client - it can't open the SQLite
file directly the way report.py does. Every other script in this project (ingest_*,
embed, classify, trend, recommend) already does the real work; this module just
wraps their outputs and DB reads as HTTP endpoints.
"""

from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastembed import TextEmbedding
from pydantic import BaseModel

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
from embed import MODEL_NAME
from recommend import cosine_sim, recommend as compute_recommendations

app = FastAPI(title="OSS Radar API")

# Permissive for local dev since the PWA's origin isn't decided yet; tighten this
# once a real deploy target/domain is chosen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_search_model: Optional[TextEmbedding] = None


def get_search_model() -> TextEmbedding:
    global _search_model
    if _search_model is None:
        _search_model = TextEmbedding(model_name=MODEL_NAME)
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
