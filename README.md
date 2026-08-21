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
- [ ] 趨勢分數（依 star/download 成長率，而非絕對值）
- [ ] 個人化推薦
- [ ] API（FastAPI）
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
- （規劃中）FastAPI、趨勢分數、個人化推薦、PWA 前端
