import { useState } from "react";
import { search } from "../api";
import ItemCard from "./ItemCard";

export default function Search() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  function runSearch(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setSearched(true);
    search(q, 20)
      .then(setResults)
      .finally(() => setLoading(false));
  }

  return (
    <div className="search">
      <form onSubmit={runSearch} className="search-form" role="search">
        <label htmlFor="search-q" className="visually-hidden">
          搜尋關鍵字
        </label>
        <input
          id="search-q"
          type="search"
          placeholder="用自然語言描述，例如：長期記憶的 agent"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">
          搜尋
        </button>
      </form>
      <p className="search-hint">語意搜尋：比對意思而不是字面，論文、專案、模型一起找。</p>

      {loading && <div className="state-msg">搜尋中…</div>}
      {!loading && searched && results.length === 0 && <div className="state-msg">找不到相關項目</div>}

      <div className="item-list">
        {results.map((item) => (
          <ItemCard key={`${item.source}:${item.source_id}`} item={item} compact />
        ))}
      </div>
    </div>
  );
}
