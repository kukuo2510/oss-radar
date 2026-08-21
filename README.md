# OSS Radar

自動追蹤 arXiv 論文、GitHub repo、HuggingFace models/datasets 中「最近熱門」或「符合個人興趣」的項目，
統一做語意分類與個人化推薦，並用手機可讀的介面呈現。

這是一個求職用的 side project，目標是展示資料擷取、embedding/語意分類、趨勢訊號設計、個人化推薦與 API/前端部署的完整流程。詳細規劃見 [PLAN.md](./PLAN.md)。

## 目前進度

- [x] arXiv ingestion（`src/ingest_arxiv.py`）
- [x] GitHub ingestion（`src/ingest_github.py`）
- [x] HuggingFace ingestion（`src/ingest_hf.py`）
- [x] 統一的 SQLite schema（`items` + `metric_snapshots`）
- [x] 排程自動抓取（`src/scheduler.py`，本地開發版）
- [x] Embedding（`src/embed.py`）+ 零樣本語意分類（`src/classify.py`）
- [x] 趨勢分數（`src/trend.py`，依 star/download 成長率，冷啟動時退回百分位排名）
- [x] 簡易本地 HTML 報表（`src/report.py`，開發用，非正式 app UI）
- [x] 個人化推薦（`src/recommend.py` + `src/interact.py` 手動標記工具）
- [x] API（`src/api.py`，FastAPI）
- [ ] 前端（PWA）

## 架構

```
[ingest_arxiv / ingest_github / ingest_hf]
              |
              v
   SQLite: items（各來源統一格式）
           metric_snapshots（star/download 隨時間變化，供之後算成長率用）
```

三個來源共用同一張 `items` 表（`source` 欄位區分來源），方便之後做跨來源的 embedding 與推薦，不用為每個來源分開處理。

## 安裝與執行

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash；PowerShell 用 venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd src
python ingest_arxiv.py
python ingest_github.py
python ingest_hf.py
```

資料會存到 `data/oss_radar.db`（SQLite，未進版本控制）。

### 排程（本地開發）

```bash
cd src
python scheduler.py   # 常駐執行，每天 02:00/02:10/02:20 依序跑三個來源
```

排程與 app 完全脫鉤：app 只透過 API 讀 DB 當下的資料，不負責、也不需要知道資料是怎麼進來的。
部署到正式環境後，同一套 job 邏輯會改成在後端 process 內跑，或交給平台的 cron 功能（GitHub Actions
scheduled workflow、Render Cron Jobs 等）呼叫同樣的 `ingest_*.main()`。

### Embedding + 分類

```bash
cd src
python embed.py      # 幫還沒算過 embedding 的 item 補上（BAAI/bge-small-en-v1.5, 384 維）
python classify.py   # 零樣本分類：算 item embedding 與 11 個預先定義主題的 cosine similarity，取分數最高的 1-3 個當標籤
```

用 `fastembed`（ONNX runtime）而不是 `sentence-transformers`（預設要裝 torch）：模型小、CPU 就能跑、
不用額外裝一整套深度學習框架，對之後要部署在低成本主機上比較友善。

分類用零樣本（跟 topic 描述算相似度）而不是無監督分群：不需要標註資料，而且每個 item 直接對應到人類看得懂
的主題名稱，能直接拿來當 app 裡的分類 tab，不用像分群結果那樣還要自己命名每一群在講什麼。

已知限制：目前各主題分數集中在 0.65-0.77，區分度不夠明顯，之後可以調整主題描述文字或換更大的 embedding model 來改善。

### 趨勢分數

```bash
cd src
python trend.py
```

依 GitHub star / HF download 的成長速度（每天變化量）排序，而非看絕對數字——一個從 10 星衝到 200 星
的新 repo 應該排在一個長年停在 5000 星沒動靜的 repo 前面。計算成長率需要至少兩筆間隔一段時間的
`metric_snapshots`，剛跑第一次（或排程還沒跑滿一整天）的 item 沒有歷史可比，會退回用「目前數值的百分位
排名」當替代分數（冷啟動問題，之後有更多天的快照資料後會自動改用真正的成長率）。arXiv 論文因為沒有
熱度數字可以追蹤，不計算趨勢分數。

### 個人化推薦

app 的按讚/略過 UI 還沒做出來，先用 CLI 工具手動標記，讓推薦邏輯現在就能用真實資料測試：

```bash
cd src
python interact.py --like "arxiv:2608.19564v1" --skip "github:some/repo"
python recommend.py
```

做法：把喜歡項目的 embedding 取平均當作「使用者興趣向量」（略過的項目則反向拉開一點），
再用 cosine similarity 對還沒看過的項目排序，最後跟 `trend.py` 的趨勢分數加權混合
（60% 個人化 + 40% 趨勢），讓「符合興趣」跟「正在熱門」都有影響力，不會兩者只看一個。

冷啟動（完全沒有按讚/略過紀錄）：沒有興趣向量可以算，直接退回純趨勢排序——跟 `trend.py`
自己處理冷啟動的方式一致，同一套邏輯重複用。

已用真實資料驗證過：標記幾筆 LLM/Agent 相關論文與 repo 為讚、機器人相關為略過後，
推薦結果確實都帶有 "Large Language Models" 或 "AI Agents & Tool Use" 標籤，符合預期。

### API

```bash
cd src
python -m uvicorn api:app --reload
```

啟動後預設在 `http://127.0.0.1:8000`，互動式文件在 `/docs`（FastAPI 內建，Swagger UI）。

| 端點 | 說明 |
|---|---|
| `GET /items` | 列表，可用 `source`、`tag`、`limit`、`offset` 過濾/分頁 |
| `GET /items/{source}/{source_id}` | 單筆詳細資料（含標籤）|
| `GET /tags` | 各主題標籤與數量，給前端做分類 tab |
| `GET /trending` | 趨勢排行（`trend.py` 的結果）|
| `GET /recommendations` | 個人化推薦（`recommend.py` 的結果）|
| `GET /search?q=...` | 跨來源語意搜尋（即時 embed 查詢字串，跟全部 item 算 cosine similarity）|
| `POST /interactions` | 記錄按讚/略過，body: `{"source", "source_id", "action"}` |

這一層存在的原因：app 是瀏覽器/手機端，沒辦法像 `report.py` 那樣直接開 SQLite 檔案，所有邏輯都要透過
HTTP 暴露出去。API 本身不做任何新邏輯，純粹包裝已經寫好的 `ingest_*` / `embed` / `classify` / `trend` /
`recommend` 模組。

語意搜尋目前是即時把全部 item 的 embedding 讀進記憶體算 cosine similarity（線性掃描），資料量還很小
（幾百筆）完全夠用；之後資料量大到某個程度，才需要換成向量資料庫（pgvector/Chroma）做索引，現階段換
反而是過度設計。

已用真實 HTTP request 驗證過全部端點（`/items`、`/trending`、`/recommendations`、`/search`、
`POST /interactions`、含斜線的 `source_id` 路由）都正常運作。

### 本地報表（開發用）

```bash
cd src
python report.py   # 產生 data/report.html，看目前資料狀態、分類分布、趨勢排行
```

不是正式 app UI，純粹是開發階段快速肉眼檢查資料品質用的靜態頁面。

### 環境變數（選用）

- `GITHUB_TOKEN`：GitHub Search API 未帶 token 時速率限制較低（10 req/min）。設定後可提高額度：
  ```bash
  export GITHUB_TOKEN=ghp_xxxx
  ```

## Tech Stack

- Python 3.14
- SQLite（之後視需要換 Postgres + pgvector）
- requests / feedparser
- APScheduler（排程）
- fastembed（ONNX runtime，BAAI/bge-small-en-v1.5 embedding）
- FastAPI + uvicorn
- （規劃中）PWA 前端
