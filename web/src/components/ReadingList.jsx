import { useCallback, useEffect, useState } from "react";
import { addReading, deleteReading, getReaderWorker, getReadingList, retryReading } from "../api";
import { AlertIcon, ExternalIcon, MonitorIcon, PlusIcon } from "./Icons";

const TABS = [
  { key: "unread", label: "待讀" },
  { key: "working", label: "處理中" },
  { key: "done", label: "已讀" },
];

const SOURCE_LABEL = { x: "X", arxiv: "arXiv" };
const READ_DONE = 0.98;

function tabOf(item) {
  if (item.status !== "ready") return "working";
  return item.read_progress >= READ_DONE ? "done" : "unread";
}

function timeAgo(iso) {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "剛剛";
  if (min < 60) return `${min} 分鐘前`;
  if (min < 60 * 24) return `${Math.round(min / 60)} 小時前`;
  return `${Math.round(min / 1440)} 天前`;
}

function statusText(item) {
  switch (item.status) {
    case "queued":
      return "排隊中 · 等翻譯站處理";
    case "fetching":
      return "抓取全文中…";
    case "translating":
      return `翻譯中 · ${item.progress_done} / ${item.progress_total} 段`;
    case "ready":
      if (item.read_progress >= READ_DONE) return "已讀完";
      return item.read_progress > 0.01 ? `已讀 ${Math.round(item.read_progress * 100)}%` : "翻譯完成 · 尚未開始";
    default:
      return "";
  }
}

function progressPct(item) {
  if (item.status === "translating" && item.progress_total) return (item.progress_done / item.progress_total) * 100;
  if (item.status === "ready") return item.read_progress * 100;
  return 0;
}

export default function ReadingList({ onOpen, refreshKey }) {
  const [items, setItems] = useState([]);
  const [worker, setWorker] = useState(null);
  const [tab, setTab] = useState("unread");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [url, setUrl] = useState("");
  const [addError, setAddError] = useState(null);

  const load = useCallback(() => {
    return Promise.all([getReadingList(), getReaderWorker()])
      .then(([list, w]) => {
        setItems(list);
        setWorker(w);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  // 有項目在處理時每 15 秒更新一次進度；全部處理完就停，不浪費請求。
  const busy = items.some((it) => it.status !== "ready" && it.status !== "failed");
  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [busy, load]);

  async function submit(e) {
    e.preventDefault();
    if (!url.trim()) return;
    setAddError(null);
    try {
      await addReading(url.trim());
      setUrl("");
      setAdding(false);
      setTab("working");
      load();
    } catch (err) {
      setAddError(err.message);
    }
  }

  async function act(fn, id) {
    try {
      await fn(id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const counts = Object.fromEntries(TABS.map((t) => [t.key, items.filter((it) => tabOf(it) === t.key).length]));
  const visible = items.filter((it) => tabOf(it) === tab);

  return (
    <div className="reading-list">
      <div className="reading-actions">
        <button className="btn btn-primary btn-icon" onClick={() => setAdding((v) => !v)} aria-expanded={adding}>
          <PlusIcon size={18} />
          貼上網址
        </button>
      </div>

      {adding && (
        <form className="add-form" onSubmit={submit}>
          <label htmlFor="reading-url" className="visually-hidden">
            文章網址
          </label>
          <input
            id="reading-url"
            type="url"
            inputMode="url"
            placeholder="X 貼文或 arXiv 論文網址"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" type="submit">
            加入
          </button>
          {addError && <p className="form-error">{addError}</p>}
        </form>
      )}

      <div className="worker-card">
        <MonitorIcon />
        <div className="worker-text">
          <strong>{worker?.online ? "翻譯站在線" : "翻譯站離線"}</strong>
          <span>
            {worker?.last_seen
              ? `你的電腦 · ${worker.model} · ${timeAgo(worker.last_seen)}回報`
              : "還沒有回報過，請在電腦上執行 reader_worker.py"}
          </span>
        </div>
        <span className={`dot ${worker?.online ? "dot-on" : ""}`} aria-hidden="true" />
      </div>

      <div className="tabbar" role="tablist" aria-label="深讀狀態">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`tab ${tab === t.key ? "tab-active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label} <span className="mono">{counts[t.key]}</span>
          </button>
        ))}
      </div>

      {loading && <div className="state-msg">載入中…</div>}
      {error && <div className="state-msg error">{error}</div>}
      {!loading && visible.length === 0 && (
        <div className="state-msg">
          {tab === "unread" ? "沒有待讀的文章" : tab === "working" ? "沒有處理中的文章" : "還沒有讀完的文章"}
        </div>
      )}

      <div className="item-list">
        {visible.map((it) => {
          const ready = it.status === "ready";
          const title = it.title_zh || it.title || it.url;
          return (
            <article key={it.id} className="item-card reading-card">
              <span className="item-meta mono">
                {[SOURCE_LABEL[it.source] || "等待抓取", it.authors?.[0], timeAgo(it.created_at) + "加入"]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {ready ? (
                <button className="reading-title" onClick={() => onOpen(it.id)}>
                  {title}
                </button>
              ) : (
                <span className="reading-title">{title}</span>
              )}
              {it.title_zh && it.title && <span className="reading-subtitle">{it.title}</span>}
              {it.one_line && <p className="reading-oneline">{it.one_line}</p>}
              <a className="source-link" href={it.url} target="_blank" rel="noreferrer">
                {it.url.replace(/^https?:\/\//, "")}
                <ExternalIcon />
              </a>

              {it.status === "failed" ? (
                <div className="error-box">
                  <AlertIcon />
                  <span>{it.error || "處理失敗"}</span>
                  <button className="btn btn-sm" onClick={() => act(retryReading, it.id)}>
                    重試
                  </button>
                  <button className="btn btn-sm" onClick={() => act(deleteReading, it.id)}>
                    移除
                  </button>
                </div>
              ) : (
                <div className="progress-wrap">
                  <div className="progress-track">
                    <div
                      className={`progress-bar ${it.read_progress >= READ_DONE ? "progress-done" : ""}`}
                      style={{ width: `${progressPct(it)}%` }}
                    />
                  </div>
                  <span className="progress-text">{statusText(it)}</span>
                </div>
              )}
            </article>
          );
        })}
      </div>

      <p className="share-hint">在 X App 按「分享」並選 OSS Radar，就能把文章丟進來。電腦開著時會自動抓全文並翻譯。</p>
    </div>
  );
}
