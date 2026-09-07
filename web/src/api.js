// 後端 API 的基底網址：優先使用建置時注入的環境變數 VITE_API_BASE，
// 沒有設定時預設打本機開發用的後端（127.0.0.1:8000）。
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

// 共用的 GET 請求小工具：組出完整網址、檢查回應狀態、回傳解析後的 JSON。
// 下面所有 GET 類型的 API 呼叫都透過這個函式，避免重複寫 fetch + 錯誤處理邏輯。
async function request(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

// 取得個人化推薦清單。
export function getRecommendations(limit = 20) {
  return request(`/recommendations?limit=${limit}`);
}

// 取得所有標籤與各自的使用次數，給篩選用的標籤清單。
export function getTags() {
  return request("/tags");
}

// 依來源（source）/標籤（tag）分頁列出項目清單。
export function getItems({ source, tag, limit = 30 } = {}) {
  const params = new URLSearchParams({ limit });
  if (source) params.set("source", source);
  if (tag) params.set("tag", tag);
  return request(`/items?${params}`);
}

// 語意搜尋：q 是查詢字串，需要用 encodeURIComponent 處理特殊字元避免網址被破壞。
export function search(q, limit = 20) {
  return request(`/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

// 記錄使用者對某個項目的按讚/略過行為。
// 這裡沒有透過共用的 request()，是因為這是 POST 請求、需要帶 body 跟自訂 headers，
// 跟其他單純的 GET 查詢請求形狀不同。
export async function recordInteraction(source, sourceId, action) {
  const res = await fetch(`${API_BASE}/interactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id: sourceId, action }),
  });
  if (!res.ok) throw new Error(`interactions -> ${res.status}`);
  return res.json();
}
