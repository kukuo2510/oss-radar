import SourceBadge from "./SourceBadge";

export default function ItemCard({ item, compact = false }) {
  return (
    <a className={`item-card ${compact ? "compact" : ""}`} href={item.url} target="_blank" rel="noreferrer">
      <div className="item-card-header">
        <SourceBadge source={item.source} />
        {item.metric != null && <span className="metric">★ {item.metric.toLocaleString()}</span>}
      </div>
      <h3>{item.title}</h3>
      {!compact && <p className="description">{item.description}</p>}
      {item.tags?.length > 0 && (
        <div className="tag-row">
          {item.tags.slice(0, 3).map((t) => (
            <span key={t.tag} className="tag-pill">
              {t.tag}
            </span>
          ))}
        </div>
      )}
    </a>
  );
}
