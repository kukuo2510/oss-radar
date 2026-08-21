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
          placeholder="Search across papers, repos, models..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      {loading && <div className="state-msg">Searching...</div>}
      {!loading && searched && results.length === 0 && <div className="state-msg">No results.</div>}

      <div className="item-list">
        {results.map((item) => (
          <ItemCard key={`${item.source}:${item.source_id}`} item={item} compact />
        ))}
      </div>
    </div>
  );
}
