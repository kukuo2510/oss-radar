# 設計決策與踩過的坑

給自己之後回頭看，或想知道「為什麼這樣做」的細節，不放進 README 是因為太長了。

## 統一 schema

三個來源（arxiv/github/huggingface）共用同一張 `items` 表（`source` 欄位區分），沒有各自開一張表。
這樣之後做跨來源 embedding、推薦時不用為每個來源分開處理。

## Embedding 用 fastembed 不是 sentence-transformers

fastembed 是 ONNX runtime，不用裝一整套 torch，模型小、CPU 就能跑，對之後要部署在低成本主機上比較
友善。（後來部署到 Render 免費方案才發現，這個選擇是對的——torch 版本大概率直接讓機器爆掉。）

## 分類用零樣本不是分群

算 item embedding 跟一組手動定義的 11 個主題描述的 cosine similarity，取分數最高的 1-3 個當標籤。
不需要標註資料，而且每個 item 直接對應到人類看得懂的主題名稱，能直接拿來當 app 裡的分類 tab，不用
像分群結果那樣還要自己命名每一群在講什麼。

已知限制：目前各主題分數集中在 0.65-0.77，區分度不夠明顯，之後可以調整主題描述文字或換更大的
embedding model 來改善。

## 趨勢分數的冷啟動

依 GitHub star / HF download 的成長速度排序，而非看絕對數字。但計算成長率需要至少兩筆間隔一段時間的
`metric_snapshots`，剛跑第一次的 item 沒有歷史可比，會退回用「目前數值的百分位排名」當替代分數，
之後有更多天的快照資料後會自動改用真正的成長率。arXiv 論文沒有熱度數字，不計算趨勢分數。

## 個人化推薦

把喜歡項目的 embedding 取平均當「使用者興趣向量」（略過的項目反向拉開一點），用 cosine similarity
排序，再跟趨勢分數加權混合（60% 個人化 + 40% 趨勢）。冷啟動（無互動紀錄）退回純趨勢排序，跟
`trend.py` 自己的冷啟動邏輯一致，重複用同一套。

已用真實資料驗證過：標記幾筆 LLM/Agent 相關內容為讚、機器人相關為略過後，推薦結果確實都帶對應標籤。

## API 層

語意搜尋是即時把全部 item embedding 讀進記憶體算 cosine similarity（線性掃描），資料量還很小（幾百筆）
完全夠用；之後資料量大到一定程度才需要換向量資料庫（pgvector/Chroma），現階段換反而是過度設計。

端點參考（互動文件見部署後的 `/docs`）：

| 端點 | 說明 |
|---|---|
| `GET /items` | 列表，可用 `source`、`tag`、`limit`、`offset` 過濾/分頁 |
| `GET /items/{source}/{source_id}` | 單筆詳細資料（含標籤）|
| `GET /tags` | 各主題標籤與數量 |
| `GET /trending` | 趨勢排行 |
| `GET /recommendations` | 個人化推薦 |
| `GET /search?q=...` | 跨來源語意搜尋 |
| `POST /interactions` | 記錄按讚/略過，body: `{"source", "source_id", "action"}` |
| `POST /admin/run-step/{step}` | 跑 pipeline 其中一步，需要 `X-Admin-Token` header |

## 前端

滑卡片手勢自己用 pointer events 寫（`ForYou.jsx`），沒裝手勢函式庫——這個互動夠簡單，加套件的成本
大於自己寫。Service worker 只快取 app shell，刻意不快取 API 回應，因為這個 app 的價值就是新鮮資料。

## 部署踩過的坑（Render 免費方案）

1. **一次 request 跑完整條 pipeline 直接 OOM**：一開始是單一個 `/admin/run-pipeline` 端點，一次 HTTP
   request 內把 ingestion + embed + classify + trend 全部跑完，結果 Render 免費方案（512MB RAM）直接
   跑到當機。改成 `/admin/run-step/{step}`，一次一步，每次呼叫結束後 process 有機會釋放記憶體。
2. **拆開後單一步驟還是 OOM**：`embed` 這步自己跑還是爆記憶體，問題不是疊加，是 onnxruntime 預設的
   記憶體 arena（預先配置的記憶體池）本身就超過免費方案能給的量。改成 `enable_cpu_mem_arena=0`、
   `threads=1`（見 `src/embed.py` 的 `load_model()`）。
3. **記憶體解決後換成太慢**：Render 免費方案 CPU 只有 0.15 顆核心，一次跑完 300 多筆 embedding 直接
   超過合理的 request timeout。改成 `embed.py` 每次呼叫最多處理 15 筆（`MAX_ITEMS_PER_RUN`，數字是
   部署後實測量出來的），回傳還剩幾筆，呼叫端（GitHub Actions）迴圈呼叫直到清空。
4. **免費方案沒有持久化硬碟**：`data/oss_radar.db` 在重新部署時會被清空。對個人使用來說可以接受；
   真的常常需要保留資料的話，選項是加 Render 付費 Disk，或換成免費的外部 Postgres（Neon/Supabase）。
5. **任何 push 都會觸發重新部署，包含只改文件**：Render 預設對 master 的每次 push 都自動重新部署，
   哪怕只是改 README、沒動到任何程式邏輯，一樣會讓資料庫被清空。解法：Render Settings 裡把
   Auto-Deploy 關掉，改成後端程式碼真的有變動時才手動按 Deploy。

**已在正式環境完整驗證過**（2026-08-21）：從空白資料庫開始，跑完 3 個來源 ingestion → 25 次 embed
呼叫（371 筆資料，每次 15 筆）→ classify → trend，全部端點回應正常，資料跟本地開發環境結果一致，
前端（Vercel）也確認能正常讀到 Render 上的資料。
