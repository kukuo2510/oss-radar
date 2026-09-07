// 最精簡的 Service Worker：只快取「App 外殼」（app shell），
// 讓使用者「加到主畫面」後，就算網路不穩也能立刻啟動。
// 刻意不快取任何 API 回應——這個 App 的核心價值就是資料要即時，離線同步不在規劃範圍內。
const CACHE = "oss-radar-shell-v2";
const SHELL = ["/", "/manifest.json", "/icon.svg"];

// 安裝階段：把 App 外殼需要的檔案全部快取起來，並立即跳過等待（skipWaiting）
// 讓新版本的 Service Worker 儘快生效。
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

// 啟用階段：清掉舊版本留下來、名稱跟目前 CACHE 常數不一致的快取，
// 避免累積過期資源；並立刻接管所有分頁（clients.claim）。
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

// 攔截請求：只處理同來源（origin）的 GET 請求（跨網域或非 GET 的請求一律放行，
// 交給瀏覽器正常處理），優先回傳快取，快取沒有才真的發出網路請求。
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
