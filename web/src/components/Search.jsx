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
      <form onSubmit={runSearch} className="search-form">
        <input
          type="search"
          placeholder="查閱論文、程式庫、模型…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn" type="submit">
          查閱
        </button>
      </form>

      {loading && <div className="state-msg">查閱中…</div>}
      {!loading && searched && results.length === 0 && <div className="state-msg">查無所獲</div>}

      <div className="item-list">
        {results.map((item) => (
          <ItemCard key={`${item.source}:${item.source_id}`} item={item} compact />
        ))}
      </div>
    </div>
  );
}
