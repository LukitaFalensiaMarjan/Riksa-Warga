/* Service worker Riksa Warga.
   - Aplikasi & data GET terakhir: network-first, cadangan cache saat offline (diberi header x-rw-offline).
   - Tile peta: cache-first untuk tile yang PERNAH dibuka. Tidak ada unduh massal (kebijakan tile OSM).
   - POST saat offline ditangani halaman (antrean di perangkat), bukan di sini. */
const SHELL = "rw-shell-v42", API = "rw-api", TILES = "rw-tiles", EXT = "rw-ext";
const MAX_TILES = 2500;
const PRECACHE = ["/", "/js/config.js", "/js/lib/api.js", "/js/lib/avatar.js", "/js/lib/chart.js", "/js/lib/dom.js", "/js/lib/format.js", "/js/lib/geo.js", "/js/lib/icons.js", "/js/lib/map.js", "/js/lib/offline.js", "/js/lib/store.js", "/js/lib/tracker.js", "/js/lib/notifwatch.js", "/js/lib/modal.js", "/js/lib/theme.js", "/js/lib/ui.js", "/js/main.js", "/js/router.js", "/js/session.js", "/js/state.js", "/js/tabs.js", "/js/views/admin/admin.js", "/js/views/koordinator/dashboard.js", "/js/views/koordinator/incidents.js", "/js/views/koordinator/priorities.js", "/js/views/koordinator/registrations.js", "/js/views/koordinator/reports.js", "/js/views/koordinator/residents.js", "/js/views/koordinator/routeadmin.js", "/js/views/koordinator/tasks.js", "/js/views/koordinator/weather.js", "/js/views/pos_pantau/stations.js", "/js/views/pos_pantau/verify.js", "/js/views/tim_sar/helpmap.js", "/js/views/tim_sar/reports.js", "/js/views/koordinator/households.js", "/js/views/tim_sar/myTasks.js", "/js/views/umum/alerts.js", "/js/views/umum/authArt.js", "/js/views/umum/login.js", "/js/views/umum/mapnav.js", "/js/views/umum/nature.js", "/js/views/umum/notifications.js", "/js/views/umum/report.js", "/js/views/umum/shell.js", "/js/views/umum/shelters.js", "/js/views/umum/taskCard.js", "/js/views/warga/home.js", "/js/views/warga/mine.js", "/js/views/warga/kit.js", "/js/views/warga/alerts.js", "/js/views/warga/myReports.js", "/js/views/warga/peta.js", "/js/views/warga/report.js", "/js/views/warga/shelters.js", "/style.css", "/auth.css", "/warga.css", "/manifest.json", "/icons/logo-192.png", "/icons/logo-mark.png",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"];
const API_PATH = /^\/(alerts|shelters|evacuation-routes|road-conditions|stations|me\/resident|reports\/mine|tasks|config|regions|auth\/me|weather|dashboard|incidents|evacuation\/priorities|residents|help-requests|rules)/;

self.addEventListener("install", e => e.waitUntil(
  caches.open(SHELL).then(c => Promise.allSettled(PRECACHE.map(u => c.add(u)))).then(() => self.skipWaiting())));

self.addEventListener("activate", e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (![SHELL, API, TILES, EXT].includes(k)) await caches.delete(k);
  await self.clients.claim();
})()));

async function networkFirst(req, name) {
  const cache = await caches.open(name);
  try {
    const res = req.mode === "navigate" ? await fetch(req) : await fetch(req, { cache: "no-cache" });  // selalu cek versi terbaru ke server
    if (res.ok) {
      const h = new Headers(res.headers); h.set("x-rw-time", new Date().toISOString());
      cache.put(req, new Response(await res.clone().blob(), { status: res.status, headers: h }));
    }
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreVary: true });
    if (!hit) throw err;
    const h = new Headers(hit.headers); h.set("x-rw-offline", "1");
    return new Response(await hit.blob(), { status: hit.status, headers: h });
  }
}

async function tileFirst(req) {
  const cache = await caches.open(TILES);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    await cache.put(req, res.clone());
    const keys = await cache.keys();
    for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);  // buang yang terlama
  }
  return res;
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/routing/") || url.pathname.includes("/photo")) return;  // butuh jaringan
    e.respondWith(networkFirst(req, API_PATH.test(url.pathname) ? API : SHELL));
  } else if (url.hostname.includes("tile") || url.hostname.includes("cartocdn") || url.hostname.includes("arcgisonline")) {
    e.respondWith(tileFirst(req));
  } else if (url.hostname.endsWith("cdnjs.cloudflare.com") || url.hostname.includes("fonts.g")) {
    e.respondWith(networkFirst(req, EXT));
  }
});

self.addEventListener("message", e => {
  if (e.data === "logout") caches.delete(API);  // data API milik akun sebelumnya tidak boleh terbaca akun lain
});
