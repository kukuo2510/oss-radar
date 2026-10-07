import { useEffect, useRef, useState } from "react";
import { getReading, saveReadingProgress } from "../api";
import { ArrowLeftIcon, CheckIcon, CopyIcon, ExternalIcon, ExternalLinkIcon, PromptIcon, TypeIcon } from "./Icons";

const MODES = [
  { key: "zh", label: "中文" },
  { key: "both", label: "對照" },
  { key: "en", label: "原文" },
];
const THEMES = [
  { key: "auto", label: "跟隨系統" },
  { key: "light", label: "淺色" },
  { key: "dark", label: "深色" },
  { key: "soft", label: "柔光" },
];
const SETTINGS_KEY = "oss-radar-reader-settings";

// 閱讀偏好只存在這台裝置的瀏覽器裡；讀不到（無痕模式等）就用預設值。
function loadSettings() {
  try {
    return { mode: "zh", theme: "auto", fontSize: 18, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { mode: "zh", theme: "auto", fontSize: 18 };
  }
}

function saveSettings(s) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    // 存不了就算了，下次用預設值
  }
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button className="copy-btn" onClick={copy}>
      {copied ? <CheckIcon /> : <CopyIcon />}
      {copied ? "已複製" : "複製"}
    </button>
  );
}

// 一個可翻譯的文字區塊：中文模式下點一下展開原文，對照模式中英並列，原文模式只顯示英文。
function Bilingual({ zh, en, mode, as: Tag = "p", className = "" }) {
  const [open, setOpen] = useState(false);
  if (zh == null || mode === "en") return <Tag className={`r-en-only ${className}`}>{en}</Tag>;
  if (mode === "both")
    return (
      <div className={`r-pair ${className}`}>
        <Tag className="r-zh">{zh}</Tag>
        <p className="r-en">{en}</p>
      </div>
    );
  // 標題不做點擊展開（<button> 裡不能放標題元素）；段落用 span 顯示成區塊，才能放進按鈕。
  if (typeof Tag === "string" && Tag.startsWith("h")) return <Tag className={`r-zh ${className}`}>{zh}</Tag>;
  return (
    <div className={`r-pair ${className}`}>
      <button className="r-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="r-zh r-block">{zh}</span>
      </button>
      {open && <p className="r-en">{en}</p>}
    </div>
  );
}

function Block({ block, tr, mode }) {
  const ok = tr?.status === "ok";
  const zhText = ok ? tr.text : null;
  const untranslated = block.translate && !ok;
  const badge = untranslated ? <span className="r-badge">未翻譯</span> : null;

  switch (block.type) {
    case "heading": {
      const Tag = block.level <= 1 ? "h2" : block.level === 2 ? "h3" : "h4";
      return <Bilingual zh={zhText} en={block.text} mode={mode} as={Tag} className="r-heading" />;
    }
    case "paragraph":
    case "quote":
      return (
        <div className={block.type === "quote" ? "r-quote" : ""}>
          {badge}
          <Bilingual zh={zhText} en={block.text} mode={mode} />
        </div>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      const zhItems = ok ? tr.items : null;
      return (
        <Tag className="r-list">
          {block.items.map((en, i) => (
            <li key={i}>
              <Bilingual zh={zhItems?.[i] ?? null} en={en} mode={mode} as="span" />
            </li>
          ))}
        </Tag>
      );
    }
    case "image":
      return (
        <figure className="r-figure">
          {block.src && <img src={block.src} alt={block.text ? block.text.slice(0, 120) : ""} loading="lazy" />}
          {block.text && (
            <figcaption>
              <Bilingual zh={zhText} en={block.text} mode={mode} />
            </figcaption>
          )}
        </figure>
      );
    case "table":
      return (
        <figure className="r-figure">
          {block.text && (
            <figcaption>
              <Bilingual zh={zhText} en={block.text} mode={mode} />
            </figcaption>
          )}
          <div className="r-table-wrap">
            <table>
              <tbody>
                {(block.rows || []).map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </figure>
      );
    case "math":
      return (
        <div className="r-math">
          <code>{block.text}</code>
          {block.label && <span className="r-math-label">{block.label}</span>}
        </div>
      );
    case "prompt":
    case "code":
      return (
        <figure className="r-code">
          <figcaption>
            {block.type === "prompt" && <PromptIcon />}
            <span className="r-code-label">{block.type === "prompt" ? "提示詞" : "程式碼"}</span>
            <span className="r-code-note">保留原文，不翻譯</span>
            <CopyButton text={block.text} />
          </figcaption>
          <pre>{block.text}</pre>
        </figure>
      );
    case "embed":
      return (
        <a className="r-embed" href={block.url} target="_blank" rel="noreferrer">
          引用的貼文
          <ExternalIcon />
        </a>
      );
    case "divider":
      return <hr className="r-divider" />;
    default:
      return null;
  }
}

// 重點整理：本機模型依原文整理的一句話＋幾個重點，每點附上依據的原文段落；點重點跳到那段。
function SummaryCard({ summary, onJump }) {
  if (!summary?.key_points?.length) return null;
  return (
    <section className="r-summary" aria-label="重點整理">
      <div className="r-summary-head">
        <span className="r-summary-title">重點整理</span>
        <span className="r-summary-note">本機 AI 依原文整理，可能有誤</span>
      </div>
      {summary.one_line && <p className="r-summary-line">{summary.one_line}</p>}
      <ol className="r-summary-points">
        {summary.key_points.map((p, i) => (
          <li key={i}>
            {p.blocks?.length ? (
              <button onClick={() => onJump(p.blocks[0])}>
                <span>{p.text}</span>
                <span className="r-summary-jump">看原段落 ↓</span>
              </button>
            ) : (
              <span>{p.text}</span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Reader({ id, onBack }) {
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [settings, setSettings] = useState(loadSettings);
  const [showSettings, setShowSettings] = useState(false);
  const [progress, setProgress] = useState(0);
  const scrollRef = useRef(null);
  const saveTimer = useRef(null);
  const restored = useRef(false);

  useEffect(() => {
    getReading(id)
      .then(setItem)
      .catch((e) => setError(e.message));
  }, [id]);

  // 打開時捲回上次讀到的位置（只做一次）。
  useEffect(() => {
    const el = scrollRef.current;
    if (!item || !el || restored.current) return;
    restored.current = true;
    const target = item.read_progress < 0.98 ? item.read_progress : 0;
    requestAnimationFrame(() => {
      el.scrollTop = target * (el.scrollHeight - el.clientHeight);
    });
  }, [item]);

  function update(patch) {
    const next = { ...settings, ...patch };
    setSettings(next);
    saveSettings(next);
  }

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const max = el.scrollHeight - el.clientHeight;
    const p = max > 0 ? el.scrollTop / max : 1;
    setProgress(p);
    // 停止捲動 1.5 秒後才存進度，不會每滑一下就打一次 API。
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveReadingProgress(id, p).catch(() => {});
    }, 1500);
  }

  useEffect(() => () => clearTimeout(saveTimer.current), []);

  const theme = settings.theme;
  const doc = item?.doc;
  const tr = item?.translation;
  const blocks = doc?.blocks || [];
  const trBlocks = tr?.blocks || {};
  const total = blocks.filter((b) => b.translate).length;
  const okCount = Object.values(trBlocks).filter((b) => b.status === "ok").length;
  const zhChars = Object.values(trBlocks).reduce((n, b) => n + (b.text?.length || 0), 0);
  const minutes = Math.max(1, Math.round(zhChars / 400));

  // 區塊 id → 它是第幾個重點的依據（一段可能同時支撐好幾個重點）。
  const keyMap = {};
  (tr?.summary?.key_points || []).forEach((p, i) =>
    (p.blocks || []).forEach((bid) => (keyMap[bid] = [...(keyMap[bid] || []), i + 1]))
  );

  function jumpTo(blockId) {
    const el = document.getElementById(`blk-${blockId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.remove("r-flash");
    void el.offsetWidth; // 重新觸發閃爍動畫
    el.classList.add("r-flash");
  }

  return (
    <div className="reader" data-theme={theme} style={{ "--read-size": `${settings.fontSize}px` }}>
      <div className="reader-progress" aria-hidden="true">
        <div style={{ width: `${progress * 100}%` }} />
      </div>
      <header className="reader-bar">
        <button className="icon-btn" aria-label="返回深讀清單" onClick={onBack}>
          <ArrowLeftIcon />
        </button>
        <span className="reader-bar-title">{item?.title_zh || item?.title || ""}</span>
        <button
          className="icon-btn"
          aria-label="字級與主題"
          aria-expanded={showSettings}
          onClick={() => setShowSettings((v) => !v)}
        >
          <TypeIcon />
        </button>
        {item && (
          <a className="reader-source-btn" href={item.url} target="_blank" rel="noreferrer">
            原文
            <ExternalLinkIcon size={16} />
          </a>
        )}
      </header>

      {showSettings && (
        <div className="reader-settings">
          <div className="seg" role="group" aria-label="閱讀主題">
            {THEMES.map((t) => (
              <button
                key={t.key}
                className={theme === t.key ? "seg-on" : ""}
                aria-pressed={theme === t.key}
                onClick={() => update({ theme: t.key })}
              >
                {t.label}
              </button>
            ))}
          </div>
          <label className="size-row">
            <span>字級</span>
            <input
              type="range"
              min="16"
              max="22"
              step="1"
              value={settings.fontSize}
              onChange={(e) => update({ fontSize: Number(e.target.value) })}
            />
            <span className="mono">{settings.fontSize}px</span>
          </label>
        </div>
      )}

      <main className="reader-body" ref={scrollRef} onScroll={onScroll}>
        {error && <div className="state-msg error">載入失敗：{error}</div>}
        {!item && !error && <div className="state-msg">載入中…</div>}
        {item && !doc && <div className="state-msg">這篇還在處理中，翻譯完成後就能閱讀。</div>}

        {doc && (
          <article className="reader-article">
            <div className="reader-meta">
              <span className="mono">
                {[doc.source === "x" ? "X" : "arXiv", doc.authors?.slice(0, 2).join("、"), formatDate(doc.published_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <h1>{tr?.title_zh || doc.title}</h1>
              {tr?.title_zh && <p className="reader-title-en">{doc.title}</p>}
              <div className="chips">
                <span>約 {minutes} 分鐘</span>
                {tr?.model && <span>本機翻譯 · {tr.model}</span>}
                {tr?.glossary && <span>術語表 {tr.glossary.length} 條</span>}
              </div>
              {doc.warnings?.map((w) => (
                <p key={w} className="reader-warning">
                  {w}
                </p>
              ))}
            </div>

            <SummaryCard summary={tr?.summary} onJump={jumpTo} />

            <div className="seg seg-wide" role="group" aria-label="閱讀模式">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  className={settings.mode === m.key ? "seg-on" : ""}
                  aria-pressed={settings.mode === m.key}
                  onClick={() => update({ mode: m.key })}
                >
                  {m.label}
                </button>
              ))}
            </div>
            {settings.mode === "zh" && <p className="reader-tip">點任一段落可展開該段原文。</p>}

            {blocks.map((b) => (
              <div key={b.id} id={`blk-${b.id}`} className={keyMap[b.id] ? "r-keyblock" : undefined}>
                {keyMap[b.id] && <span className="r-keytag">重點 {keyMap[b.id].join("、")}</span>}
                <Block block={b} tr={trBlocks[b.id]} mode={settings.mode} />
              </div>
            ))}

            <aside className="reader-credit">
              <span className="credit-label">出處</span>
              <span className="credit-title">{doc.title}</span>
              <span className="credit-meta">
                {[doc.authors?.join("、"), formatDate(doc.published_at)].filter(Boolean).join(" · ")}
              </span>
              <a href={doc.url} target="_blank" rel="noreferrer" className="source-link">
                {doc.url.replace(/^https?:\/\//, "")}
                <ExternalIcon />
              </a>
              {doc.shared_url && (
                <a href={doc.shared_url} target="_blank" rel="noreferrer" className="source-link">
                  分享來源：{doc.shared_url.replace(/^https?:\/\//, "")}
                  <ExternalIcon />
                </a>
              )}
              <span className="credit-note">
                翻譯由本機模型產生、僅供個人閱讀，可能有誤（{okCount}/{total} 段通過自動檢查）；著作權屬原作者。
              </span>
            </aside>
          </article>
        )}
      </main>
    </div>
  );
}
