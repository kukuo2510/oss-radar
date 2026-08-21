const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function request(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export function getRecommendations(limit = 20) {
  return request(`/recommendations?limit=${limit}`);
}

export function getTags() {
  return request("/tags");
}

export function getItems({ source, tag, limit = 30 } = {}) {
  const params = new URLSearchParams({ limit });
  if (source) params.set("source", source);
  if (tag) params.set("tag", tag);
  return request(`/items?${params}`);
}

export function search(q, limit = 20) {
  return request(`/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export async function recordInteraction(source, sourceId, action) {
  const res = await fetch(`${API_BASE}/interactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id: sourceId, action }),
  });
  if (!res.ok) throw new Error(`interactions -> ${res.status}`);
  return res.json();
}
