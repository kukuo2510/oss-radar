import { useEffect, useState } from "react";
import { getItems, getTags } from "../api";
import ItemCard from "./ItemCard";

const SOURCES = [
  { value: "", label: "All" },
  { value: "arxiv", label: "arXiv" },
  { value: "github", label: "GitHub" },
  { value: "huggingface_models", label: "HF Models" },
  { value: "huggingface_datasets", label: "HF Datasets" },
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
      <div className="chip-row">
        {SOURCES.map((s) => (
          <button
            key={s.value}
            className={`chip ${source === s.value ? "chip-active" : ""}`}
            onClick={() => setSource(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="chip-row scroll">
        <button className={`chip ${tag === "" ? "chip-active" : ""}`} onClick={() => setTag("")}>
          All topics
        </button>
        {tags.map((t) => (
          <button
            key={t.tag}
            className={`chip ${tag === t.tag ? "chip-active" : ""}`}
            onClick={() => setTag(t.tag)}
          >
            {t.tag} ({t.count})
          </button>
        ))}
      </div>

      {loading ? (
        <div className="state-msg">Loading...</div>
      ) : items.length === 0 ? (
        <div className="state-msg">No items match this filter.</div>
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
