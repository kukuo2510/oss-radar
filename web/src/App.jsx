import { useEffect, useState } from "react";
import "./App.css";
import "./Reading.css";
import { addReading } from "./api";
import ForYou from "./components/ForYou";
import Browse from "./components/Browse";
import Search from "./components/Search";
import ReadingList from "./components/ReadingList";
import Reader from "./components/Reader";
import { BookOpenIcon, CompassIcon, LogoMark, RadarIcon, SearchIcon } from "./components/Icons";

const TABS = [
  { key: "foryou", label: "今日", title: "今日雷達", Icon: RadarIcon },
  { key: "browse", label: "探索", title: "探索", Icon: CompassIcon },
  { key: "reading", label: "深讀", title: "深讀", Icon: BookOpenIcon },
  { key: "search", label: "搜尋", title: "搜尋", Icon: SearchIcon },
];

const WEEKDAYS = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"];

function todayLabel() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} · ${WEEKDAYS[d.getDay()]}`;
}

// 手機「分享」到這個 PWA 時（manifest 的 share_target），網址會帶 ?url=…&text=…。
// X App 通常把連結放在 text 裡，所以兩個都看。
function sharedText() {
  const params = new URLSearchParams(window.location.search);
  return [params.get("url"), params.get("text"), params.get("title")].filter(Boolean).join(" ");
}

export default function App() {
  // 從分享進來就直接開在「深讀」分頁。
  const [tab, setTab] = useState(() => (sharedText() ? "reading" : "foryou"));
  const [readingId, setReadingId] = useState(null);
  const [toast, setToast] = useState(null);
  const [listVersion, setListVersion] = useState(0);
  const current = TABS.find((t) => t.key === tab);

  useEffect(() => {
    const shared = sharedText();
    if (!shared) return;
    window.history.replaceState(null, "", "/");
    addReading(shared)
      .then(() => setToast("已加入深讀清單，電腦開著時會自動翻譯"))
      .catch((e) => setToast(`沒有加入：${e.message}`))
      .finally(() => setListVersion((v) => v + 1));
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // 閱讀頁用瀏覽器歷史紀錄開啟，Android 的返回鍵／手勢才會回到清單，而不是直接離開 App。
  useEffect(() => {
    const onPop = () => setReadingId(null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function openReading(id) {
    window.history.pushState({ reading: id }, "");
    setReadingId(id);
  }

  function closeReading() {
    if (window.history.state?.reading) window.history.back();
    else setReadingId(null);
    setListVersion((v) => v + 1);
  }

  if (readingId) return <Reader id={readingId} onBack={closeReading} />;

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
        {tab === "reading" && <ReadingList onOpen={openReading} refreshKey={listVersion} />}
        {tab === "search" && <Search />}
      </main>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

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
