import { useState } from "react";
import "./App.css";
import ForYou from "./components/ForYou";
import Browse from "./components/Browse";
import Search from "./components/Search";

const TABS = [
  { key: "foryou", label: "For You", icon: "✨" },
  { key: "browse", label: "Browse", icon: "📚" },
  { key: "search", label: "Search", icon: "🔍" },
];

export default function App() {
  const [tab, setTab] = useState("foryou");

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>OSS Radar</h1>
      </header>

      <main className="app-main">
        {tab === "foryou" && <ForYou />}
        {tab === "browse" && <Browse />}
        {tab === "search" && <Search />}
      </main>

      <nav className="bottom-nav">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`nav-btn ${tab === t.key ? "nav-active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            <span className="nav-icon">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
