import SourceBadge from "./SourceBadge";
import { CloseIcon, ExternalIcon, ThumbUpIcon } from "./Icons";

// GitHub 是星數、Hugging Face 是下載次數；一萬以上用「萬」顯示，比較符合中文的讀法。
function formatMetric(source, metric) {
  if (metric == null) return null;
  const n = metric >= 10000 ? `${Math.round(metric / 10000).toLocaleString()} 萬` : metric.toLocaleString();
  return source === "github" ? `★ ${n}` : `↓ ${n}`;
}

// 每張卡片都附原始連結（使用者明確要求）：顯示去掉 https:// 的網址，點了另開分頁。
function displayUrl(url) {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export default function ItemCard({ item, compact = false, liked = false, onLike, onSkip }) {
  const metric = formatMetric(item.source, item.metric);
  const isPaper = item.source === "arxiv";
  const showMatch = item.basis === "personalized" && item.score != null;

  return (
    <article className={`item-card ${compact ? "compact" : ""}`}>
      <div className="item-meta">
        <SourceBadge source={item.source} />
        {metric && <span className="mono">{metric}</span>}
        {showMatch && <span className="match mono">契合 {Math.round(item.score * 100)}%</span>}
      </div>

      <h3 className={isPaper ? "title-paper" : "title-repo"}>{item.title}</h3>
      <a className="source-link" href={item.url} target="_blank" rel="noreferrer">
        {displayUrl(item.url)}
        <ExternalIcon />
      </a>

      {!compact && item.description && item.description !== item.title && (
        <p className="description">{item.description}</p>
      )}

      {!compact && item.narration && (
        <div className="why">
          <span className="why-label">推薦理由</span>
          <p>{item.narration}</p>
        </div>
      )}

      {(onLike || onSkip) && (
        <div className="card-actions">
          {onLike && (
            <button
              className={`icon-btn ${liked ? "icon-btn-on" : ""}`}
              aria-label="讚"
              aria-pressed={liked}
              onClick={onLike}
            >
              <ThumbUpIcon size={20} />
            </button>
          )}
          {onSkip && (
            <button className="icon-btn" aria-label="略過" onClick={onSkip}>
              <CloseIcon size={20} />
            </button>
          )}
        </div>
      )}
    </article>
  );
}
