import { useEffect, useState } from "react";
import { getItems, getRecommendations, getTrending, recordInteraction } from "../api";
import ItemCard from "./ItemCard";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "paper", label: "論文" },
  { key: "repo", label: "專案" },
  { key: "model", label: "模型" },
];

const isModel = (it) => it.source === "huggingface_models" || it.source === "huggingface_datasets";

export default function ForYou() {
  const [recs, setRecs] = useState([]);
  const [papers, setPapers] = useState([]);
  const [models, setModels] = useState([]);
  const [liked, setLiked] = useState({});
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    load();
  }, []);

  function load() {
    setLoading(true);
    setError(null);
    Promise.all([getRecommendations(20), getItems({ source: "arxiv", limit: 5 }), getTrending(40)])
      .then(([r, p, t]) => {
        setRecs(r);
        setPapers(p);
        setModels(t.filter(isModel).slice(0, 4));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  const key = (it) => `${it.source}:${it.source_id}`;

  function like(item) {
    const k = key(item);
    const next = !liked[k];
    setLiked((m) => ({ ...m, [k]: next }));
    // 取消讚不另外記錄：後端只認「最新一次」的 like/skip，取消時不需要寫入。
    if (next) recordInteraction(item.source, item.source_id, "like").catch(() => {});
  }

  function skip(item) {
    setRecs((list) => list.filter((it) => key(it) !== key(item)));
    // 盡力而為：畫面上已經移除，寫入失敗只代表這一筆不會影響下次推薦。
    recordInteraction(item.source, item.source_id, "skip").catch(() => {});
  }

  if (loading) return <div className="state-msg">正在整理今天的雷達…</div>;
  if (error)
    return (
      <div className="state-msg error">
        載入失敗：{error}
        <button className="btn" onClick={load}>
          重試
        </button>
      </div>
    );

  const visibleRecs = recs.filter((it) =>
    filter === "all" ? true : filter === "paper" ? it.source === "arxiv" : filter === "repo" ? it.source === "github" : isModel(it)
  );
  const showPapers = filter === "all" || filter === "paper";
  const showModels = filter === "all" || filter === "model";

  return (
    <div className="for-you">
      <div className="chip-row" role="group" aria-label="來源篩選">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip ${filter === f.key ? "chip-active" : ""}`}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <section className="feed-section">
        <div className="section-head">
          <h2>為你推薦</h2>
          <span>依你的按讚即時調整</span>
        </div>
        {visibleRecs.length === 0 ? (
          <div className="state-msg">
            這個分類目前沒有推薦
            <button className="btn" onClick={load}>
              重新整理
            </button>
          </div>
        ) : (
          <div className="item-list">
            {visibleRecs.map((item) => (
              <ItemCard
                key={key(item)}
                item={item}
                liked={!!liked[key(item)]}
                onLike={() => like(item)}
                onSkip={() => skip(item)}
              />
            ))}
          </div>
        )}
      </section>

      {showPapers && papers.length > 0 && (
        <section className="feed-section">
          <div className="section-head">
            <h2>今日論文</h2>
            <span>arXiv 最新</span>
          </div>
          <div className="item-list">
            {papers.map((item) => (
              <ItemCard key={key(item)} item={item} compact />
            ))}
          </div>
        </section>
      )}

      {showModels && models.length > 0 && (
        <section className="feed-section">
          <div className="section-head">
            <h2>熱門模型</h2>
            <span>Hugging Face · 依成長率</span>
          </div>
          <div className="item-list">
            {models.map((item) => (
              <ItemCard key={key(item)} item={item} compact />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
