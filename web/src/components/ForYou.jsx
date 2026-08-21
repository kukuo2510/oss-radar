import { useEffect, useRef, useState } from "react";
import { getRecommendations, recordInteraction } from "../api";
import SourceBadge from "./SourceBadge";

const SWIPE_THRESHOLD = 100;

export default function ForYou() {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dragX, setDragX] = useState(0);
  const dragging = useRef(false);
  const startX = useRef(0);

  useEffect(() => {
    load();
  }, []);

  function load() {
    setLoading(true);
    setError(null);
    getRecommendations(20)
      .then(setQueue)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  function act(action) {
    const current = queue[0];
    if (!current) return;
    setQueue((q) => q.slice(1));
    setDragX(0);
    recordInteraction(current.source, current.source_id, action).catch(() => {
      // best-effort: swipe already happened client-side, a failed write here
      // just means this one won't count toward the next profile refresh
    });
  }

  function onPointerDown(e) {
    dragging.current = true;
    startX.current = e.clientX;
  }
  function onPointerMove(e) {
    if (!dragging.current) return;
    setDragX(e.clientX - startX.current);
  }
  function onPointerUp() {
    if (!dragging.current) return;
    dragging.current = false;
    if (dragX > SWIPE_THRESHOLD) act("like");
    else if (dragX < -SWIPE_THRESHOLD) act("skip");
    else setDragX(0);
  }

  if (loading) return <div className="state-msg">Loading recommendations...</div>;
  if (error) return <div className="state-msg error">Failed to load: {error}</div>;
  if (queue.length === 0)
    return (
      <div className="state-msg">
        No more items right now.
        <button className="btn" onClick={load}>
          Refresh
        </button>
      </div>
    );

  const current = queue[0];
  const rotation = dragX / 15;
  const likeOpacity = Math.min(Math.max(dragX / SWIPE_THRESHOLD, 0), 1);
  const skipOpacity = Math.min(Math.max(-dragX / SWIPE_THRESHOLD, 0), 1);

  return (
    <div className="for-you">
      <div
        className="swipe-card"
        style={{ transform: `translateX(${dragX}px) rotate(${rotation}deg)` }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        <span className="stamp stamp-like" style={{ opacity: likeOpacity }}>
          LIKE
        </span>
        <span className="stamp stamp-skip" style={{ opacity: skipOpacity }}>
          SKIP
        </span>
        <div className="item-card-header">
          <SourceBadge source={current.source} />
          {current.metric != null && <span className="metric">★ {current.metric.toLocaleString()}</span>}
        </div>
        <h3>{current.title}</h3>
        <p className="description">{current.description}</p>
        {current.tags?.length > 0 && (
          <div className="tag-row">
            {current.tags.slice(0, 3).map((t) => (
              <span key={t.tag} className="tag-pill">
                {t.tag}
              </span>
            ))}
          </div>
        )}
        <p className="basis-note">
          {current.basis === "personalized" ? "matched to your taste" : "trending now"}
        </p>
      </div>

      <div className="swipe-actions">
        <button className="btn btn-skip" onClick={() => act("skip")}>
          ✕ Skip
        </button>
        <button className="btn btn-like" onClick={() => act("like")}>
          ♥ Like
        </button>
      </div>
      <p className="queue-count">{queue.length} left in this batch</p>
    </div>
  );
}
