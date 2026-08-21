# OSS Radar

自動追蹤 arXiv 論文、GitHub repo、HuggingFace models/datasets 中「最近熱門」或「符合個人興趣」的項目，
統一做語意分類與個人化推薦，並用手機可讀的介面呈現。

這是一個求職用的 side project，目標是展示資料擷取、embedding/語意分類、趨勢訊號設計、個人化推薦與 API/前端部署的完整流程。詳細規劃見 [PLAN.md](./PLAN.md)。

## 目前進度

- [x] arXiv ingestion（`src/ingest_arxiv.py`）
- [x] GitHub ingestion（`src/ingest_github.py`）
- [x] HuggingFace ingestion（`src/ingest_hf.py`）
- [x] 統一的 SQLite schema（`items` + `metric_snapshots`）
- [ ] 排程自動抓取
- [ ] Embedding + 語意分類
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

### 環境變數（選用）

- `GITHUB_TOKEN`：GitHub Search API 未帶 token 時速率限制較低（10 req/min）。設定後可提高額度：
  ```bash
  export GITHUB_TOKEN=ghp_xxxx
  ```

## Tech Stack

- Python 3.14
- SQLite（之後視需要換 Postgres + pgvector）
- requests / feedparser
- （規劃中）FastAPI、embedding model、PWA 前端
