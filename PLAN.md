# OSS Radar — 開源趨勢雷達（求職 Side Project）

## 專案目標
自動追蹤 arXiv 論文、GitHub repo、HuggingFace models/datasets 中「最近熱門」或「符合個人興趣」的項目，
統一做語意分類與個人化推薦，並用手機可讀的介面（PWA）呈現。

## 為什麼做這個（求職角度）
應徵方向：資料/AI/ML 工程師（新手/轉職）。這個專案能在履歷上涵蓋：
- 多來源資料擷取（API 串接、排程任務）
- Embedding / 向量表示、語意分類
- 趨勢訊號設計（成長速度，而非絕對數字）
- 個人化推薦（content-based / 簡易 collaborative filtering）
- LLM 摘要與 prompt engineering
- API 部署（FastAPI）+ 前端（PWA）

比起單純的分類器或 CRUD app，這個組合更接近真實 recommender system 工程師的工作內容。

## 資料來源
| 來源 | 方式 | 備註 |
|---|---|---|
| arXiv | 官方 API | 依分類/關鍵字定期抓新論文 |
| GitHub | Search API（`created:>日期` + star 排序）| 無官方 trending API，用 search 模擬 |
| HuggingFace | Hub API（models/datasets）| 可依 downloads/likes 排序 |

## 系統架構（草案）
```
[排程 ingestion] --> [統一 embedding 空間] --> [分類/趨勢分數] --> [DB + 向量儲存]
                                                                        |
                                                                        v
                                                        [FastAPI: 列表/搜尋/推薦 API]
                                                                        |
                                                                        v
                                                              [前端 PWA（手機用）]
```

- Embedding：句子/文件層級，來源不論是論文摘要、README、或 model card，統一轉成同一種向量
- 趨勢分數：計算過去 7 天 star/download 增量，而非絕對值
- 個人化：使用者按讚/略過的行為記錄 → 內容相似度 + 簡單排序模型

## 分階段計畫（抓 4 週，可依實際步調調整）

**Week 1 — Ingestion**
- 串接 arXiv / GitHub / HuggingFace API
- 存原始資料進 DB（先用 SQLite 或 Postgres）
- 排程機制（cron 或 APScheduler）

**Week 2 — Embedding + 分類/趨勢**
- 選定 embedding model（sentence-transformers 或 API 型）
- 建向量儲存（Chroma / pgvector）
- 設計趨勢分數計算邏輯
- 分類/打標籤邏輯

**Week 3 — 個人化 + API**
- 使用者互動紀錄（讚/略過）
- 推薦排序邏輯
- FastAPI 對外 API（列表、搜尋、推薦）
- LLM 摘要功能

**Week 4 — 前端 + 部署 + 收尾**
- PWA 前端（列表 + tab 分類 + 手機加到主畫面）
- 部署（前後端各找一個免費/低成本平台）
- 寫 README、整理成果，準備履歷/面試講法

## 待補充（下次可以先想一下）
- [ ] 興趣關鍵字 / 主題 seed list（例如：LLM、RL、影像生成…）
- [ ] 個人化要做成單人自用版，還是要支援多使用者帳號？
- [ ] 部署平台偏好（Vercel/Render/Railway/自架）
- [ ] Embedding model 用付費 API 還是本地開源模型（成本考量）

## 技術棧初步建議
- 後端：Python + FastAPI
- 資料庫：Postgres（含 pgvector）或 SQLite + Chroma
- 排程：APScheduler 或簡單 cron
- 前端：PWA（React/Vite 或更輕量的方案）
- LLM：Claude/OpenAI API 做摘要與分類輔助
