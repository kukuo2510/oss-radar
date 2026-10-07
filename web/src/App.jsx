import { useState } from "react";
import "./App.css";
import ForYou from "./components/ForYou";
import Browse from "./components/Browse";
import Search from "./components/Search";
import { CompassIcon, LogoMark, RadarIcon, SearchIcon } from "./components/Icons";

const TABS = [
  { key: "foryou", label: "今日", title: "今日雷達", Icon: RadarIcon },
  { key: "browse", label: "探索", title: "探索", Icon: CompassIcon },
  { key: "search", label: "搜尋", title: "搜尋", Icon: SearchIcon },
];

const WEEKDAYS = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"];

function todayLabel() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} · ${WEEKDAYS[d.getDay()]}`;
}

export default function App() {
  const [tab, setTab] = useState("foryou");
  const current = TABS.find((t) => t.key === tab);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <LogoMark />
          <span className="brand-name">OSS Radar</span>
        </div>
        <div className="page-heading">
          <span className="page-date">{todayLabel()}</span>
          <h1>{current.title}</h1>
        </div>
      </header>

      <main className="app-main">
        {tab === "foryou" && <ForYou />}
        {tab === "browse" && <Browse />}
        {tab === "search" && <Search />}
      </main>

      <nav className="bottom-nav" aria-label="主要導覽">
        {TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            className={`nav-btn ${tab === key ? "nav-active" : ""}`}
            aria-current={tab === key ? "page" : undefined}
            onClick={() => setTab(key)}
          >
            <Icon />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
