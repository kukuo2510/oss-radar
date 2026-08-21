# OSS Radar

> 🚧 開發中，個人使用專案，非正式產品

自動追蹤 arXiv 論文、GitHub repo、HuggingFace models/datasets 中「最近熱門」或「符合個人興趣」的項目，
統一做語意分類與個人化推薦，用手機可讀的介面呈現。

**Demo**
- App：https://oss-radar-theta.vercel.app
- API：https://oss-radar-api.onrender.com/docs

## 特色

- 自動抓取 arXiv / GitHub / HuggingFace 三個來源的最新動態
- 零樣本語意分類，跨來源統一打上主題標籤
- 依成長率（而非絕對熱度）排序的趨勢分數，新竄紅的項目會排在長年不動的熱門項目前面
- 內容式個人化推薦，按讚/略過會即時影響後續推薦
- 跨來源語意搜尋
- PWA 前端，可加到手機主畫面，滑卡片操作

## Tech Stack

- Python + FastAPI、SQLite
- fastembed（embedding）
- APScheduler / GitHub Actions（排程）
- React + Vite（前端 PWA）
- Vercel + Render（部署）

## 本地開發

```bash
python -m venv venv && source venv/Scripts/activate   # PowerShell 用 venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd src
python ingest_arxiv.py && python ingest_github.py && python ingest_hf.py
python embed.py && python classify.py && python trend.py
python -m uvicorn api:app --reload
```

前端：

```bash
cd web
npm install
npm run dev -- --host
```

設計決策與部署細節見 [NOTES.md](./NOTES.md)。
