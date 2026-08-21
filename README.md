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
- [x] API（`src/api.py`，FastAPI，含 `/admin/run-pipeline` 供外部排程觸發）
- [x] 前端（`web/`，React + Vite PWA）
- [x] 部署設定檔（`render.yaml`、GitHub Actions 排程、Vercel 環境變數說明）——設定檔已備妥，實際申請帳號/連網域待使用者操作

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
部署到正式環境後（見下方「部署」），改成由 GitHub Actions 排程呼叫 API 的 `POST /admin/run-pipeline`
端點，而不是本地這支常駐的 `scheduler.py`——因為免費主機方案通常沒有內建 cron 功能。

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
| `POST /admin/run-step/{step}` | 跑 pipeline 的其中一步（`arxiv`/`github`/`huggingface`/`embed`/`classify`/`trend` 之一），需要 `X-Admin-Token` header 對上 `ADMIN_TOKEN` 環境變數；沒設定 `ADMIN_TOKEN` 時整個端點回 503。給外部排程（見「部署」）呼叫用，不是給前端用的。刻意設計成一次只跑一步，見下方部署章節的說明 |

這一層存在的原因：app 是瀏覽器/手機端，沒辦法像 `report.py` 那樣直接開 SQLite 檔案，所有邏輯都要透過
HTTP 暴露出去。API 本身不做任何新邏輯，純粹包裝已經寫好的 `ingest_*` / `embed` / `classify` / `trend` /
`recommend` 模組。

語意搜尋目前是即時把全部 item 的 embedding 讀進記憶體算 cosine similarity（線性掃描），資料量還很小
（幾百筆）完全夠用；之後資料量大到某個程度，才需要換成向量資料庫（pgvector/Chroma）做索引，現階段換
反而是過度設計。

已用真實 HTTP request 驗證過全部端點（`/items`、`/trending`、`/recommendations`、`/search`、
`POST /interactions`、含斜線的 `source_id` 路由）都正常運作。

### 前端（PWA）

```bash
cd web
npm install
npm run dev -- --host   # --host 讓同一區網的手機也能連
```

預設在 `http://localhost:5173`，會呼叫 `http://127.0.0.1:8000` 的 API（可用 `VITE_API_BASE` 環境變數覆蓋）。
手機測試：先啟動 API（`uvicorn api:app --host 0.0.0.0`）和前端都用 `--host`，手機連同一個 Wi-Fi，
瀏覽器開 `http://<你的電腦區網 IP>:5173`，選「加到主畫面」就會有 app 圖示跟 standalone 模式。

三個分頁：
- **For You**：卡片式推薦（`/recommendations`），左滑略過、右滑喜歡（或按鈕），寫回 `POST /interactions`
- **Browse**：來源 + 主題 tab 過濾（`/tags`、`/items`）
- **Search**：跨來源語意搜尋（`/search`）

滑卡片手勢是自己用 pointer events 寫的（`ForYou.jsx` 的 `onPointerDown/Move/Up`），沒有另外裝手勢函式庫——
這個互動夠簡單（單軸拖曳判斷左右閾值），加一個套件的成本大於自己寫。

PWA 三件套：`public/manifest.json`（app 名稱/圖示/standalone 模式）、`public/icon.svg`、
`public/sw.js`（極簡 service worker，只快取 app shell 讓開啟更快，刻意不快取 API 回應——這個 app 的
價值就是新鮮資料，離線同步不在規劃內）。

已用 Chrome 實際打開測試過三個分頁：For You 滑卡片會正確呼叫 API 並前進到下一張、Browse 的來源/主題
過濾即時生效、Search 搜尋「vector database for semantic search」有撈到 reranker model 和相關論文，
console 沒有錯誤。

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

## 部署

推薦組合：**Vercel（前端）+ Render（後端 API）**，兩者都有免費方案。排程改用 GitHub Actions（見上方
「排程」段落），不用另外找付費 cron 服務。

### 1. 後端：Render

1. 把這個 repo push 到 GitHub（如果還沒有）
2. Render 主控台 → New → Blueprint → 選這個 repo，會讀到根目錄的 [`render.yaml`](./render.yaml) 自動建立服務
3. Render 會自動產生 `ADMIN_TOKEN`（在 render.yaml 裡設定 `generateValue: true`）——部署完後去
   Render 的環境變數頁面複製這個值，等一下 GitHub Actions 要用
4. 部署完會拿到一個網址，例如 `https://oss-radar-api.onrender.com`

**已知限制**：Render 免費方案沒有付費的持久化硬碟，`data/oss_radar.db` 在重新部署或機器搬遷時可能被清空。
對一個作品集 demo 來說可以接受；如果之後真的常常掉資料，兩個選項：(a) 加 Render 的付費 Disk 方案，
或 (b) 把 SQLite 換成免費的外部 Postgres（Neon、Supabase 都有不會過期的免費方案），這個之前在
PLAN.md 就已經標註是「之後視需要」的選項，不是新問題。

### 2. 前端：Vercel

1. Vercel 主控台 → New Project → 選這個 repo，Root Directory 設成 `web`（Vercel 會自動偵測是 Vite 專案）
2. 在專案的環境變數設定 `VITE_API_BASE` = 你 Render 後端的網址（上一步拿到的）
3. 部署完會拿到一個網址，例如 `https://oss-radar.vercel.app`
4. 回頭把這個網址填回 Render 後端的 `ALLOWED_ORIGINS` 環境變數（取代 render.yaml 裡的預設 `*`），
   讓 CORS 只放行你自己的前端，不是任何網站都能打你的 API

### 3. 排程：GitHub Actions

[`.github/workflows/daily-pipeline.yml`](./.github/workflows/daily-pipeline.yml) 已經寫好，每天 UTC 02:00
（台灣時間早上 10 點）依序呼叫 6 次 `/admin/run-step/{step}`（`arxiv` → `github` → `huggingface` →
`embed` → `classify` → `trend`），一次一步，不是一次呼叫跑完全部。

**這個設計是真的踩過坑才改的**：一開始是單一個 `/admin/run-pipeline` 端點，一次 HTTP request 內把 6
步驟全部跑完，結果部署到 Render 免費方案（512MB RAM）時直接把 instance 跑到 OOM 當機（`embed.py` 跟
`classify.py` 各自都會載入一份 embedding 模型，疊在同一個 request 裡記憶體不夠用）。拆成 6 次獨立呼叫後，
每次呼叫結束後 process 有機會釋放記憶體，尖峰用量只會是單一步驟需要的量，不會疊加。要啟用：

1. GitHub repo → Settings → Secrets and variables → Actions，新增兩個 secret：
   - `API_BASE_URL`：Render 後端網址（不要有結尾斜線），例如 `https://oss-radar-api.onrender.com`
   - `ADMIN_TOKEN`：跟 Render 環境變數裡的 `ADMIN_TOKEN` 一樣的值
2. 也可以到 repo 的 Actions 頁面手動觸發一次（`workflow_dispatch`），確認設定正確

### 4. 接自己的網域

上面兩步都會先拿到 Vercel/Render 給的預設網址（`*.vercel.app` / `*.onrender.com`），可以先用這個測試，
確認都正常後，再到 Vercel／Render 的專案設定加自訂網域（例如 `app.你的網域.com`），然後去你買網域的
DNS 設定頁面加對應的 CNAME 紀錄——Vercel/Render 都有現成的教學頁面會列出要加哪些紀錄，照著填就好。

## Tech Stack

- Python 3.14
- SQLite（之後視需要換 Postgres + pgvector）
- requests / feedparser
- APScheduler（排程）
- fastembed（ONNX runtime，BAAI/bge-small-en-v1.5 embedding）
- FastAPI + uvicorn
- React 19 + Vite（PWA，vanilla service worker，無額外手勢/狀態管理套件）
- 部署：Vercel（前端）+ Render（後端）+ GitHub Actions（排程，取代免費方案沒有的 cron 功能）
