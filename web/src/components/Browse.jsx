import { useEffect, useState } from "react";
import { getItems, getTags } from "../api";
import ItemCard from "./ItemCard";

const SOURCES = [
  { value: "", label: "全部" },
  { value: "arxiv", label: "論文" },
  { value: "github", label: "專案" },
  { value: "huggingface_models", label: "模型" },
  { value: "huggingface_datasets", label: "資料集" },
];

export default function Browse() {
  const [tags, setTags] = useState([]);
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTags().then(setTags).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    getItems({ source: source || undefined, tag: tag || undefined, limit: 30 })
      .then(setItems)
      .finally(() => setLoading(false));
  }, [source, tag]);

  return (
    <div className="browse">
      <div className="chip-row" role="group" aria-label="來源篩選">
        {SOURCES.map((s) => (
          <button
            key={s.value}
            className={`chip ${source === s.value ? "chip-active" : ""}`}
            aria-pressed={source === s.value}
            onClick={() => setSource(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="chip-row scroll" role="group" aria-label="主題篩選">
        <button
          className={`chip chip-sm ${tag === "" ? "chip-active" : ""}`}
          aria-pressed={tag === ""}
          onClick={() => setTag("")}
        >
          全部主題
        </button>
        {tags.map((t) => (
          <button
            key={t.tag}
            className={`chip chip-sm ${tag === t.tag ? "chip-active" : ""}`}
            aria-pressed={tag === t.tag}
            onClick={() => setTag(t.tag)}
          >
            {t.tag} <span className="mono">{t.count}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="state-msg">載入中…</div>
      ) : items.length === 0 ? (
        <div className="state-msg">沒有符合的項目</div>
      ) : (
        <div className="item-list">
          {items.map((item) => (
            <ItemCard key={`${item.source}:${item.source_id}`} item={item} compact />
          ))}
        </div>
      )}
    </div>
  );
}
