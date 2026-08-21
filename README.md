# OSS Radar

自動追蹤 arXiv 論文、GitHub repo、HuggingFace models/datasets 中「最近熱門」或「符合個人興趣」的項目，
統一做語意分類與個人化推薦，並用手機可讀的介面呈現。個人使用專案。

規劃見 [PLAN.md](./PLAN.md)，設計決策與部署踩過的坑記錄在 [NOTES.md](./NOTES.md)。

**上線網址**：
- App：https://oss-radar-theta.vercel.app
- API：https://oss-radar-api.onrender.com
（互動文件在 `/docs`）

## 架構

```
[ingest_arxiv / ingest_github / ingest_hf]
              |
              v
   SQLite: items（各來源統一格式）
           metric_snapshots（star/download 隨時間變化，供算成長率用）
```

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

資料存到 `data/oss_radar.db`（SQLite，未進版本控制）。

### 排程（本地開發）

```bash
cd src
python scheduler.py   # 常駐執行，每天依序跑三個來源 -> embed -> classify -> trend
```

### Embedding + 分類

```bash
cd src
python embed.py      # 幫還沒算過 embedding 的 item 補上（BAAI/bge-small-en-v1.5, 384 維）
python classify.py   # 零樣本分類，取相似度最高的 1-3 個主題當標籤
```

### 趨勢分數

```bash
cd src
python trend.py   # 依 star/download 成長率排序，冷啟動時退回百分位排名
```

### 個人化推薦

app 的按讚/略過 UI 還沒做出來時，先用 CLI 手動標記測試：

```bash
cd src
python interact.py --like "arxiv:2608.19564v1" --skip "github:some/repo"
python recommend.py
```

### API

```bash
cd src
python -m uvicorn api:app --reload
```

預設在 `http://127.0.0.1:8000`，互動式文件在 `/docs`。

| 端點 | 說明 |
|---|---|
| `GET /items` | 列表，可用 `source`、`tag`、`limit`、`offset` 過濾/分頁 |
| `GET /items/{source}/{source_id}` | 單筆詳細資料（含標籤）|
| `GET /tags` | 各主題標籤與數量 |
| `GET /trending` | 趨勢排行 |
| `GET /recommendations` | 個人化推薦 |
| `GET /search?q=...` | 跨來源語意搜尋 |
| `POST /interactions` | 記錄按讚/略過，body: `{"source", "source_id", "action"}` |
| `POST /admin/run-step/{step}` | 跑 pipeline 其中一步（`arxiv`/`github`/`huggingface`/`embed`/`classify`/`trend`），需要 `X-Admin-Token` header 對上 `ADMIN_TOKEN` 環境變數 |

### 前端（PWA）

```bash
cd web
npm install
npm run dev -- --host   # --host 讓同一區網的手機也能連
```

會呼叫 `VITE_API_BASE` 指定的 API（預設 `http://127.0.0.1:8000`）。手機測試：API 跟前端都加 `--host`，
手機連同一個 Wi-Fi，瀏覽器開電腦的區網 IP，選「加到主畫面」。

三個分頁：
- **For You**：卡片式推薦，左滑略過、右滑喜歡，寫回 `POST /interactions`
- **Browse**：來源 + 主題 tab 過濾
- **Search**：跨來源語意搜尋

### 本地報表（開發用）

```bash
cd src
python report.py   # 產生 data/report.html，看資料狀態、分類分布、趨勢排行
```

### 環境變數（選用）

- `GITHUB_TOKEN`：GitHub Search API 未帶 token 速率限制較低（10 req/min）
  ```bash
  export GITHUB_TOKEN=ghp_xxxx
  ```

## 部署

**Vercel（前端）+ Render（後端 API）+ GitHub Actions（排程）**，都用免費方案。

### 1. 後端：Render

1. repo push 到 GitHub
2. Render 主控台 → New → Blueprint → 選這個 repo，會讀 [`render.yaml`](./render.yaml) 自動建立服務
3. Render 會自動產生 `ADMIN_TOKEN`，去環境變數頁面複製，等一下 GitHub Actions 要用
4. 部署完拿到網址，例如 `https://oss-radar-api.onrender.com`

### 2. 前端：Vercel

1. Vercel 主控台 → New Project → 選這個 repo，Root Directory 設成 `web`
2. 環境變數設定 `VITE_API_BASE` = Render 後端的網址
3. 部署完拿到網址

### 3. 排程：GitHub Actions

[`.github/workflows/daily-pipeline.yml`](./.github/workflows/daily-pipeline.yml) 每天 UTC 02:00 依序呼叫
`/admin/run-step/{step}`。要啟用，GitHub repo → Settings → Secrets and variables → Actions，新增：
- `API_BASE_URL`：Render 後端網址（不要有結尾斜線）
- `ADMIN_TOKEN`：跟 Render 環境變數裡的值一樣

### 4. 接自己的網域

先用 Vercel/Render 預設網址測試，確認正常後，再到各自的專案設定加自訂網域，去網域註冊商的 DNS 頁面
加對應紀錄。

## Tech Stack

- Python 3.14、SQLite
- requests / feedparser（ingestion）
- APScheduler（本地排程）
- fastembed（ONNX runtime，BAAI/bge-small-en-v1.5 embedding）
- FastAPI + uvicorn
- React 19 + Vite（PWA）
- 部署：Vercel + Render + GitHub Actions
