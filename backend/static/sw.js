/* Service worker Riksa Warga.
   - Aplikasi & data GET terakhir: network-first, cadangan cache saat offline (diberi header x-rw-offline).
   - Tile peta: cache-first untuk tile yang PERNAH dibuka. Tidak ada unduh massal (kebijakan tile OSM).
   - POST saat offline ditangani halaman (antrean di perangkat), bukan di sini. */
const SHELL = "rw-shell-v2", API = "rw-api", TILES = "rw-tiles", EXT = "rw-ext";
const MAX_TILES = 2500;
const PRECACHE = ["/", "/app.js", "/style.css", "/manifest.json", "/icons/logo-192.png", "/icons/logo-mark.png",
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
    const res = await fetch(req);
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
  } else if (url.hostname.includes("tile")) {
    e.respondWith(tileFirst(req));
  } else if (url.hostname.endsWith("cdnjs.cloudflare.com") || url.hostname.includes("fonts.g")) {
    e.respondWith(networkFirst(req, EXT));
  }
});

self.addEventListener("message", e => {
  if (e.data === "logout") caches.delete(API);  // data API milik akun sebelumnya tidak boleh terbaca akun lain
});
