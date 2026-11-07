"use strict";
/* Riksa Warga — UI tanpa build. Data pengguna selalu dirender lewat textContent (h()), tidak pernah
   lewat innerHTML, supaya isi laporan/nama tidak bisa menyisipkan skrip. */

const DEMO_CENTER = [-6.8830, 107.6110];
const PRESETS = [
  ["Hulu 1 (dekat pos hulu)", -6.8805, 107.6102, "RT 01 / RW 01"],
  ["Hulu 2", -6.8812, 107.6106, "RT 01 / RW 01"],
  ["Hulu 3", -6.8798, 107.6095, "RT 01 / RW 01"],
  ["Hilir 1", -6.9002, 107.6151, "RT 01 / RW 02"],
  ["Hilir 2", -6.9008, 107.6155, "RT 01 / RW 02"],
  ["Hilir 3", -6.8998, 107.6146, "RT 01 / RW 02"],
  ["Luapan Citepus Pagarsih (75cm)", -6.9240, 107.5950, "RT 02 / RW 01"],
];
const LABEL = {
  aman_mandiri: "Saya Aman (laporan mandiri)", aman_terverifikasi: "Aman Terverifikasi",
  belum_terkonfirmasi: "Belum Terkonfirmasi", butuh_bantuan: "Butuh Bantuan",
  dalam_penanganan: "Dalam Penanganan", dalam_perjalanan: "Dalam Perjalanan",
  tiba_di_titik_aman: "Tiba di Titik Aman", tidak_dapat_dihubungi: "Tidak Dapat Dihubungi",
  belum_diverifikasi: "BELUM DIVERIFIKASI", terverifikasi: "Terverifikasi",
  data_kedaluwarsa: "Data kedaluwarsa", tidak_ada_data: "Belum ada data",
  pos_pantau: "Pos pantau", simulation: "SIMULASI", real: "Nyata",
  menunggu_penerimaan: "Menunggu diterima", diterima: "Diterima", menuju_lokasi: "Menuju lokasi",
  baru: "Belum ditugaskan", selesai: "Selesai", gagal: "Gagal", dibatalkan: "Dibatalkan",
  jalan_tertutup: "Jalan tertutup", genangan: "Genangan / banjir", api: "Api", pohon_tumbang: "Pohon tumbang",
  kabel_listrik: "Kabel listrik", dilaporkan_dapat_dilalui: "Dilaporkan dapat dilalui",
  air_naik: "Air Naik", sampah_menumpuk: "Sampah Menumpuk", arus_deras: "Arus Deras",
  tanggul_rusak: "Tanggul Rusak", genangan_jalan: "Genangan Jalan", masuk_rumah: "Masuk Rumah",
  lumpur_pekat: "Endapan Lumpur",
};
const lab = v => LABEL[v] || String(v ?? "").replaceAll("_", " ");
const LEVEL_RANK = { pantau: 1, waspada: 2, siaga: 3, evakuasi: 4 };
const PRIO_COLOR = { kritis: "#dc2626", tinggi: "#ea580c", sedang: "#d97706", rendah: "#0e7c86" };
const LEVEL_COLOR = { pantau: "#64748b", waspada: "#d97706", siaga: "#ea580c", evakuasi: "#dc2626" };

// ---------- util ----------
const $ = (s, r = document) => r.querySelector(s);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "value") value = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  if (value !== undefined) el.value = value;
  return el;
}

const utc = s => new Date(/(Z|[+-]\d\d:\d\d)$/.test(s) ? s : s + "Z");  // API: UTC tanpa zona
const fmt = s => s ? utc(s).toLocaleString("id-ID", { timeZone: "Asia/Jakarta", dateStyle: "short", timeStyle: "short" }) + " WIB" : "-";
const fmtDist = m => m == null ? "-" : m >= 1000 ? (m / 1000).toFixed(1) + " km" : Math.round(m) + " m";
const fmtDur = s => s == null ? "-" : s < 60 ? "< 1 menit" : Math.round(s / 60) + " menit";
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
const num = v => (v === "" || v == null ? null : Number(v));

function toast(msg, bad = false) {
  const t = h("div", { class: bad ? "bad" : "" }, msg);
  $("#toast").append(t);
  setTimeout(() => t.remove(), bad ? 7000 : 3500);
}

const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage penuh/diblokir */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* abaikan */ } },
};

let token = store.get("rw_token");
let me = null;
let cfg = { tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", tile_attribution: "© OpenStreetMap contributors", routing_enabled: true };

async function api(method, path, body, opt = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, { method, headers, body: payload }); }
  catch { setNet(false); const e = new Error("Tidak ada koneksi ke server"); e.offline = true; throw e; }
  setNet(!r.headers.get("x-rw-offline"), r.headers.get("x-rw-time"));
  if (r.status === 401 && !opt.login) { logout(); throw new Error("Sesi berakhir, silakan login lagi"); }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const d = await r.json();
      msg = typeof d.detail === "string" ? d.detail
        : (d.detail || []).map(e => (e.loc || []).slice(1).join(".") + ": " + e.msg).join("; ");
    } catch { /* bukan JSON */ }
    throw new Error(`${r.status} — ${msg}`);
  }
  return opt.blob ? r.blob() : r.json();
}

function act(fn, okMsg) {
  return async ev => {
    const btn = ev?.currentTarget;
    if (btn?.tagName === "BUTTON") btn.disabled = true;
    try { const r = await fn(ev); if (okMsg) toast(okMsg); return r; }
    catch (e) { if (e.message !== "batal") toast(e.message, true); }
    finally { if (btn?.tagName === "BUTTON") btn.disabled = false; }
  };
}

const field = (label, input) => h("label", { class: "f" }, label, input);
const opts = (list, sel) => list.map(v => Array.isArray(v)
  ? h("option", { value: v[0], selected: String(v[0]) === String(sel) }, v[1])
  : h("option", { value: v, selected: v === sel }, lab(v)));
const badge = (text, cls = "") => h("span", { class: "badge " + cls }, text);
const lvl = l => badge(l.toUpperCase(), "b-" + l);
const verifBadge = v => badge(lab(v), v === "terverifikasi" ? "b-ok" : "b-warn");
const simBadge = on => on ? badge("SIMULASI", "b-sim") : null;
const prioBadge = p => badge(p.toUpperCase(), "p-" + p);

function table(cols, rows, empty = "Belum ada data.") {
  cols = cols.filter(Boolean);
  if (!rows.length) return h("p", { class: "muted" }, empty);
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, cols.map(c => h("th", {}, c.label)))),
    h("tbody", {}, rows.map(r => h("tr", {}, cols.map(c => h("td", {}, c.render ? c.render(r) : r[c.key])))))));
}

// ---------- geo ----------
const rad = d => d * Math.PI / 180;
function dist(a, b) {
  const dl = rad(b[0] - a[0]), dg = rad(b[1] - a[1]);
  const x = Math.sin(dl / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dg / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(x));
}
function bearing(a, b) {
  const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
  const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) - Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
const compass = deg => ["utara", "timur laut", "timur", "tenggara", "selatan", "barat daya", "barat", "barat laut"][Math.round(deg / 45) % 8];
function distToLine(p, pts) {
  if (pts.length < 2) return pts.length ? dist(p, pts[0]) : Infinity;
  let best = Infinity;
  const k = Math.cos(rad(p[0]));
  for (let i = 0; i < pts.length - 1; i++) {
    const [ay, ax] = [pts[i][0], pts[i][1] * k], [by, bx] = [pts[i + 1][0], pts[i + 1][1] * k], [py, px] = [p[0], p[1] * k];
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
    best = Math.min(best, dist(p, [ay + t * dy, (ax + t * dx) / k]));
  }
  return best;
}
function getPosition(timeout = 9000) {
  return new Promise((ok, fail) => {
    if (!navigator.geolocation) return fail(new Error("Perangkat tidak mendukung GPS"));
    navigator.geolocation.getCurrentPosition(p => ok([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
      e => fail(new Error(e.code === 1 ? "Izin lokasi ditolak" : "Lokasi GPS belum didapat")),
      { enableHighAccuracy: true, timeout, maximumAge: 30000 });
  });
}
const gmaps = (lat, lng) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=walking`;

// ---------- antrean offline (PRD §15.1) ----------
const QKEY = "rw_queue";
function enqueue(path, body, label) {
  const q = store.get(QKEY, []);
  q.push({ id: uid(), path, body, label, at: new Date().toISOString(), user: me?.id });
  store.set(QKEY, q); setNet(navigator.onLine);
}
async function flushQueue() {
  const q = store.get(QKEY, []);
  if (!q.length || !token || !me) return;
  const rest = [];
  for (const item of q) {
    if (item.user !== me.id) { rest.push(item); continue; }
    try { await api("POST", item.path, item.body); toast("Terkirim dari antrean: " + item.label); }
    catch (e) { if (e.offline) rest.push(item); else toast(`Antrean "${item.label}" ditolak: ${e.message}`, true); }
  }
  store.set(QKEY, rest); setNet(navigator.onLine);
}
// kirim; bila tidak ada koneksi simpan ke antrean perangkat
async function postOrQueue(path, body, label) {
  try { return { sent: true, data: await api("POST", path, body) }; }
  catch (e) {
    if (!e.offline) throw e;
    enqueue(path, body, label);
    toast("Tidak ada koneksi — disimpan di perangkat, dikirim otomatis saat online");
    return { sent: false };
  }
}

// ---------- status jaringan ----------
let netbar = null, netState = { online: true, at: null };
function setNet(online, at) {
  netState = { online, at: online ? null : at || netState.at };
  if (!netbar) return;
  const q = store.get(QKEY, []).filter(i => i.user === me?.id).length;
  if (online && !q) { netbar.hidden = true; return; }
  netbar.hidden = false;
  netbar.className = "netbar" + (online ? "" : " offline");
  // h() meratakan & membuang null; replaceChildren native akan menulis "null"
  netbar.replaceChildren(h("span", {}, online ? `${q} kiriman menunggu di antrean perangkat.`
    : `Offline — menampilkan data tersimpan${netState.at ? " (" + fmt(netState.at) + ")" : ""}. ${q ? q + " kiriman menunggu." : ""}`,
  online && q ? h("button", { class: "small", onclick: act(flushQueue) }, "Kirim sekarang") : null));
}
window.addEventListener("online", () => { setNet(true); flushQueue(); });
window.addEventListener("offline", () => setNet(false));

// ---------- ikon ----------
const ICONS = {
  beranda: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  alert: "M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 0 0 4 0",
  lapor: "M4 4h16v16H4zM12 8v8M8 12h8",
  peta: "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  shelter: "M3 20h18M5 20V10l7-5 7 5v10M10 20v-5h4v5",
  pos: "M12 14l4-4M3.5 18a9 9 0 1 1 17 0",
  cuaca: "M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.6 1.5A3.5 3.5 0 0 0 7 18z",
  dashboard: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  target: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 1v3M12 20v3M1 12h3M20 12h3",
  tugas: "M9 3h6v3H9zM7 5H5v16h14V5h-2M9 14l2 2 4-4",
  warga: "M16 19v-1a4 4 0 0 0-8 0v1M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 19v-1a3 3 0 0 0-2-2.8M17 5.2a3 3 0 0 1 0 5.6",
  admin: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  rute: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h2M18 9v6a4 4 0 0 1-4 4h-2",
  kejadian: "M12 9v4M12 17h.01M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  inbox: "M3 13h5l2 3h4l2-3h5M5 5h14l2 8v6H3v-6z",
  check: "M5 12l5 5L20 7",
  sos: "M12 8v5M12 16h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  arrow: "M12 3l7 18-7-4-7 4z",
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", ICONS[name] || ICONS.list);
  svg.append(p); return svg;
}

// ---------- peta ----------
let cleanups = [];
const stopMaps = () => { cleanups.forEach(f => { try { f(); } catch { /* sudah dilepas */ } }); cleanups = []; };
const tip = text => h("span", {}, text);  // elemen, bukan string HTML: aman dari XSS di tooltip Leaflet

function newMap(el, center, zoom = 15) {
  if (!window.L) { el.textContent = "Peta tidak dapat dimuat. Buka sekali saat online agar tersimpan untuk offline."; return null; }
  const map = L.map(el).setView(center || DEMO_CENTER, zoom);
  L.tileLayer(cfg.tile_url, { maxZoom: 19, attribution: cfg.tile_attribution, crossOrigin: true }).addTo(map);
  cleanups.push(() => map.remove());
  setTimeout(() => map.invalidateSize(), 80);
  return map;
}
const pinIcon = (color, glyph, pulse = false) => {
  const isYellow = color === "#eab308" || color === "#facc15" || color === "#f59e0b";
  const txtColor = isYellow ? "#78350f" : "#fff";
  return L.divIcon({
    className: "", html: `<div class="pin${pulse ? " pulse" : ""}" style="background:${color}"><span style="color:${txtColor}">${glyph}</span></div>`,
    iconSize: [30, 30], iconAnchor: [15, 30], tooltipAnchor: [0, -26],
  });
};
const dotIcon = color => L.divIcon({ className: "", html: `<div class="dotpin" style="background:${color}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
const meIcon = () => L.divIcon({ className: "", html: '<div class="me-dot"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
function addShelters(map, shelters) {
  shelters.forEach(s => L.marker([s.lat, s.lng], { icon: pinIcon(s.is_verified ? (s.status === "penuh" ? "#94a3b8" : "#0f9d6b") : "#a3b8a9", "S") })
    .addTo(map).bindTooltip(tip(`Shelter: ${s.name} · ${lab(s.status)} · ${s.occupancy || 0}/${s.capacity ?? "?"} orang${s.is_verified ? "" : " · BELUM terverifikasi"}`)));
}
function addHazards(map, hazards) {
  hazards.forEach(x => L.marker([x.lat, x.lng], { icon: pinIcon("#b91c1c", "!") })
    .addTo(map).bindTooltip(tip(`${lab(x.kind)}${x.note ? ": " + x.note : ""}`)));
}
const ROUTE_STYLE = {
  terverifikasi: { color: "#0f9d6b", weight: 6, opacity: .9 },
  dilaporkan_dapat_dilalui: { color: "#0e7c86", weight: 5, dashArray: "8 6" },
  belum_diverifikasi: { color: "#64748b", weight: 4, dashArray: "4 6" },
  ditutup: { color: "#dc2626", weight: 5, dashArray: "2 8" },
};
function addRoutes(map, routes) {
  routes.forEach(r => L.polyline(r.points, ROUTE_STYLE[r.status]).addTo(map).bindTooltip(tip(`Rute resmi: ${r.name} — ${lab(r.status)}`)));
}
const legend = items => h("div", { class: "legend" }, items.map(([c, t]) => h("span", {}, h("i", { style: `background:${c}` }), t)));

function chart(readings, station) {
  const W = 560, H = 180, P = 34, NS = "http://www.w3.org/2000/svg";
  const el = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart" });
  const max = Math.max(station.danger_cm, ...readings.map(r => r.level_cm)) * 1.12;
  const y = v => H - P - (v / max) * (H - 2 * P);
  const x = i => P + (readings.length < 2 ? (W - 2 * P) / 2 : i * (W - 2 * P) / (readings.length - 1));
  [[station.warning_cm, "#d97706", "waspada"], [station.danger_cm, "#dc2626", "bahaya"]].forEach(([v, c, t]) => {
    svg.append(el("line", { x1: P, x2: W - P, y1: y(v), y2: y(v), stroke: c, "stroke-dasharray": "5 4" }));
    svg.append(el("text", { x: W - P, y: y(v) - 4, "text-anchor": "end", "font-size": 11, fill: c, "font-weight": 700 }, `${t} ${v} cm`));
  });
  if (readings.length) {
    const pts = readings.map((r, i) => `${x(i)},${y(r.level_cm)}`).join(" ");
    svg.append(el("polygon", { points: `${x(0)},${H - P} ${pts} ${x(readings.length - 1)},${H - P}`, fill: "rgba(10,100,184,.09)" }));
    svg.append(el("polyline", { fill: "none", stroke: "#0a64b8", "stroke-width": 2.5, points: pts }));
    readings.forEach((r, i) => svg.append(el("circle", { cx: x(i), cy: y(r.level_cm), r: 4, fill: r.source_mode === "simulation" ? "#7c3aed" : "#0a64b8" })));
    const last = readings[readings.length - 1];
    svg.append(el("text", { x: P, y: 16, "font-size": 12.5, fill: "#142235", "font-weight": 700 }, `Terakhir ${last.level_cm} cm · ${fmt(last.observed_at)}${last.source_mode === "simulation" ? " · SIMULASI" : ""}`));
  } else svg.append(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "#5d6b7d" }, "Belum ada bacaan"));
  return svg;
}

// ---------- login & kerangka ----------
const app = $("#app");
let current = null, timer = null, main = null;

function logout() {
  token = null; me = null;
  store.del("rw_token");
  navigator.serviceWorker?.controller?.postMessage("logout");
  stopTimer(); stopMaps(); netbar = null;
  renderLogin();
}
const stopTimer = () => { if (timer) clearInterval(timer); timer = null; };

function renderLogin() {
  const user = h("input", { autocomplete: "username", required: true, placeholder: "Username" });
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true, placeholder: "Password (demo123)" });
  const go = act(async () => {
    const r = await api("POST", "/auth/login", { username: user.value.trim(), password: pass.value }, { login: true });
    token = r.access_token; store.set("rw_token", token);
    await boot();
  });

  const demoAccounts = [
    { role: "Tim SAR", username: "timsar1", title: "Tim SAR Satu", icon: "🚑", color: "#dc2626" },
    { role: "Koordinator Daerah", username: "koord_rw01", title: "Koordinator Wilayah RW 01", icon: "📋", color: "#0b3a6e" },
    { role: "Pos Pantau", username: "pospantau1", title: "Petugas Pos Pantau Cikapundung", icon: "🌊", color: "#0e7c86" },
    { role: "Warga", username: "warga1", title: "Warga Satu (RT 01 / RW 01)", icon: "👤", color: "#0f9d6b" },
    { role: "Admin", username: "admin", title: "Admin Kelurahan / Sistem", icon: "🛡️", color: "#475569" },
  ];

  const quickFill = (u) => {
    user.value = u;
    pass.value = "demo123";
    pass.focus();
  };

  app.replaceChildren(h("div", { class: "login-wrap" },
    h("div", { class: "login-art" },
      h("img", { src: "/icons/logo-192.png", alt: "Logo Riksa Warga" }),
      h("h1", {}, "Riksa Warga"),
      h("p", {}, "Saling jaga, saling kabari. Sistem kesiapsiagaan banjir & evakuasi Kota Bandung."),
      h("div", { class: "pills" }, h("span", {}, "Live Monitor"), h("span", {}, "Alert Broadcast"), h("span", {}, "SAR Rescue"))),
    h("div", { class: "login-form" }, h("div", { class: "card", style: "box-shadow:0 8px 30px rgba(0,0,0,.15);border-radius:14px;padding:26px" },
      h("h2", { style: "margin:0 0 6px;color:var(--navy)" }, "Masuk ke Riksa Warga"),
      h("p", { class: "muted small-text", style: "margin:0 0 16px" }, "Pilih salah satu peran demo di bawah untuk login cepat:"),

      // Demo role selection cards
      h("div", { style: "display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:18px" },
        demoAccounts.map(acc => h("div", {
          style: "display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;cursor:pointer;transition:all .15s",
          onclick: () => quickFill(acc.username),
          onmouseenter: (e) => { e.currentTarget.style.borderColor = acc.color; e.currentTarget.style.background = "#f0f7ff"; },
          onmouseleave: (e) => { e.currentTarget.style.borderColor = "#e2e8f0"; e.currentTarget.style.background = "#f8fafc"; },
        },
          h("div", { style: "display:flex;align-items:center;gap:10px" },
            h("span", { style: "font-size:22px" }, acc.icon),
            h("div", {},
              h("div", { style: `font-weight:800;font-size:14px;color:${acc.color}` }, acc.role),
              h("div", { class: "muted small-text" }, `${acc.username} · ${acc.title}`)
            )
          ),
          h("button", {
            type: "button",
            class: "small sec",
            style: "padding:4px 12px;font-size:12px;font-weight:700",
            onclick: (ev) => {
              ev.stopPropagation();
              quickFill(acc.username);
              go();
            }
          }, "Pilih & Masuk →")
        ))
      ),

      h("div", { style: "border-top:1px solid var(--line);padding-top:14px" },
        h("form", { onsubmit: ev => { ev.preventDefault(); go(); } },
          field("Username", user),
          field("Password", pass),
          h("button", { style: "width:100%;margin-top:8px" }, "Masuk")
        ),
        h("p", { class: "muted small-text", style: "text-align:center;margin-top:10px;margin-bottom:0" },
          "Password semua akun demo: ", h("b", {}, "demo123")
        )
      )
    ))
  ));
}

const TABS = {
  beranda: { label: "Beranda", icon: "beranda", render: viewHome },
  dashboard: { label: "Dashboard", icon: "dashboard", render: viewDashboard, refresh: 15000 },
  prioritas: { label: "Prioritas Evakuasi", icon: "target", render: viewPriorities },
  tugas: { label: "Tugas Tim SAR", icon: "tugas", render: viewTasks },
  tugasku: { label: "Tugas Tim SAR", icon: "tugas", render: viewMyTasks, refresh: 20000 },
  incidents: { label: "Kejadian", icon: "kejadian", render: viewIncidents },
  reports: { label: "Laporan Masuk", icon: "inbox", render: viewReports },
  residents: { label: "Data Warga & KK", icon: "warga", render: viewResidents },
  petarute: { label: "Peta & Rute", icon: "rute", render: viewRouteAdmin },
  live: { label: "Live Monitoring", icon: "pos", render: viewLiveMonitoring, refresh: 3000 },
  peta: { label: "Peta Evakuasi", icon: "peta", render: viewMapNav },
  shelters: { label: "Shelter", icon: "shelter", render: viewShelters },
  pos: { label: "Live Monitoring", icon: "pos", render: viewLiveMonitoring, refresh: 3000 },
  weather: { label: "Cuaca & Aturan", icon: "cuaca", render: viewWeather },
  alerts: { label: "Peringatan", icon: "alert", render: viewAlerts },
  lapor: { label: "Lapor Kejadian", icon: "lapor", render: viewReport },
  mine: { label: "Laporan Saya", icon: "list", render: viewMine },
  admin: { label: "Kelola User", icon: "admin", render: viewAdmin },
};
function tabsFor(role) {
  const coord = ["dashboard", "live", "prioritas", "tugas", "incidents", "reports", "residents", "petarute", "shelters", "weather", "alerts", "lapor"];
  if (role === "admin") return ["admin"];
  if (role === "koordinator") return coord;
  if (role === "tim_sar" || role === "relawan" || role === "petugas") return ["peta", "tugasku", "live", "shelters", "alerts", "lapor"];
  if (role === "pos_pantau") return ["live", "reports", "peta", "alerts", "shelters"];
  return ["beranda", "live", "peta", "mine", "alerts", "shelters", "lapor"];
}
const ROLE_LABEL = { warga: "Warga", koordinator: "Koordinator Daerah", pos_pantau: "Pos Pantau", tim_sar: "Tim SAR", relawan: "Tim SAR", petugas: "Tim SAR", admin: "Admin" };

function renderShell() {
  const tabs = tabsFor(me.role);
  const link = id => {
    const lbl = (id === "reports" && me.role === "pos_pantau") ? "Laporan & Verifikasi" : TABS[id].label;
    return h("a", { href: "#" + id, "data-id": id }, icon(TABS[id].icon), h("span", {}, lbl));
  };
  const prof = h("div", { class: "no-print" });
  const openProfile = () => { if (prof.childNodes.length) prof.replaceChildren(); else profile(prof); };
  netbar = h("div", { class: "netbar", hidden: true });
  main = h("main");
  app.replaceChildren(h("div", { class: "shell" },
    h("aside", { class: "side" },
      h("div", { class: "brand" }, h("img", { src: "/icons/logo-64.png", alt: "" }), h("div", {}, h("b", {}, "Riksa Warga"), h("span", {}, "Saling jaga, saling kabari"))),
      h("nav", { class: "nav" }, tabs.map(link)),
      h("div", { class: "me" }, h("b", {}, me.name), ROLE_LABEL[me.role] || me.role,
        h("div", { class: "row2" }, h("button", { onclick: openProfile }, "Profil"), h("button", { onclick: logout }, "Keluar")))),
    h("div", { class: "content" },
      h("div", { class: "topbar" }, h("img", { src: "/icons/logo-64.png", alt: "" }), h("b", {}, "Riksa Warga"),
        h("button", { onclick: openProfile }, "Profil"), h("button", { onclick: logout }, "Keluar")),
      h("nav", { class: "mnav" }, tabs.map(link)),
      netbar, prof, main)));
  setNet(navigator.onLine);
  const route = () => {
    if (location.hash === "#pos") location.hash = "#live";
    const id = tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : tabs[0];
    document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.id === id));
    show(id);
  };
  window.onhashchange = route;
  route();
}

function profile(box) {
  const tg = h("input", { value: me.telegram_chat_id || "", placeholder: "mis. 1949754174", inputmode: "numeric" });
  const ph = h("input", { value: me.phone || "" });
  box.replaceChildren(h("main", { style: "padding-bottom:0" }, h("div", { class: "card accent" },
    h("h3", {}, "Profil & kanal kontak"),
    h("p", { class: "muted small-text" }, "Telegram chat ID agar akun ini menerima peringatan. Kirim /start ke bot Riksa Warga lebih dulu."),
    h("div", { class: "row" }, field("Telegram chat ID", tg), field("Telepon", ph),
      h("div", { class: "btns" },
        h("button", { onclick: act(async () => { me = await api("PATCH", "/auth/me", { telegram_chat_id: tg.value.trim(), phone: ph.value.trim() }); }, "Profil tersimpan") }, "Simpan"),
        h("button", { class: "sec", onclick: act(async () => { const p = await getPosition(); await api("POST", "/me/location", { lat: p[0], lng: p[1], kind: "rumah" }); }, "Lokasi rumah disimpan dari GPS") }, "Simpan lokasi rumah (GPS)"),
        h("button", { class: "ghost", onclick: () => box.replaceChildren() }, "Tutup"))))));
}

function registerSW() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { /* butuh localhost/HTTPS */ });
}

async function boot() {
  registerSW();
  try { cfg = { ...cfg, ...(await api("GET", "/config")) }; } catch { /* pakai default */ }
  if (!token) return renderLogin();
  try { me = await api("GET", "/auth/me"); } catch (e) { toast(e.message, true); return renderLogin(); }
  renderShell();
  flushQueue();
}

async function show(id) {
  current = id; stopTimer();
  const tab = TABS[id], tmp = h("div"), posts = [];
  try { await tab.render(tmp, { post: f => posts.push(f) }); }
  catch (e) { tmp.replaceChildren(h("div", { class: "notice bad" }, "Gagal memuat: " + e.message)); }
  if (current !== id || !main?.isConnected) return;
  stopMaps();
  main.replaceChildren(...tmp.childNodes);
  for (const f of posts) await f();
  if (tab.refresh) timer = setInterval(() => { if (!document.querySelector("main input:focus, main textarea:focus, main select:focus")) show(id); }, tab.refresh);
}
const reload = () => show(current);

const REGION_ORDER = { kelurahan: 0, rw: 1, rt: 2, kecamatan: 3, kabupaten_kota: 4, provinsi: 5 };
function regionOptions(regions, sel, levels) {
  return regions.filter(r => !levels || levels.includes(r.level))
    .sort((a, b) => REGION_ORDER[a.level] - REGION_ORDER[b.level] || a.id - b.id)
    .map(r => h("option", { value: r.id, selected: r.id === sel }, `${r.name} (${r.level.toUpperCase()})`));
}

// ---------- Beranda (warga & relawan) ----------
function activeAlerts(alerts) {
  const latest = new Map();
  alerts.filter(a => !a.internal && a.incident_id).forEach(a => { if (!latest.has(a.incident_id)) latest.set(a.incident_id, a); });
  return [...latest.values()].filter(a => ["level", "koreksi"].includes(a.kind))
    .sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level]);
}
const actionLine = msg => (msg.split("\n").find(l => l.startsWith("Tindakan:")) || "").replace("Tindakan: ", "");

async function viewHome(box) {
  const [alerts, res, shelters, mode] = await Promise.all([
    api("GET", "/alerts?limit=50"),
    api("GET", "/me/resident"),
    api("GET", "/shelters"),
    api("GET", "/me/mode").catch(() => ({ active: false }))
  ]);
  const act0 = activeAlerts(alerts)[0];
  const sim = act0?.message.startsWith("[SIMULASI]");

  // Tampilkan HANYA SATU banner hero utama (prioritas: Mode Bencana > Peringatan Aktif > Wilayah Aman)
  if (mode && mode.active) {
    const mins = Math.ceil(mode.seconds_left / 60);
    box.append(h("div", { class: "hero l-evakuasi" },
      h("small", {}, "MODE BENCANA AKTIF DI AREA ANDA"),
      h("h1", {}, mode.answered ? "Terima kasih, kabar Anda sudah tercatat" : "Segera kabari keselamatan Anda"),
      h("p", {}, mode.answered ? "Tetap waspada dan ikuti arahan petugas serta pantau rute evakuasi."
        : mins > 0 ? `Tekan SAYA AMAN atau BUTUH BANTUAN dalam ±${mins} menit. Bila tidak menjawab dan lokasi Anda di area berbahaya, Anda ditandai DIDUGA BUTUH BANTUAN dan dilacak Tim SAR.`
          : "Batas waktu menjawab terlewati. Segera tekan SAYA AMAN atau BUTUH BANTUAN."),
      h("p", { style: "margin-top:8px" }, h("a", { href: "#alerts", style: "color:#fff;font-weight:700" }, "Lihat peringatan resmi →"))
    ));
  } else if (act0) {
    box.append(h("div", { class: "hero l-" + act0.level },
      h("small", {}, `${sim ? "SIMULASI · " : ""}Peringatan ${act0.verification === "terverifikasi" ? "terverifikasi" : "BELUM diverifikasi"} · ${fmt(act0.created_at)}`),
      h("h1", {}, `${act0.level.toUpperCase()} — kejadian #${act0.incident_id}`),
      h("p", {}, actionLine(act0.message) || "Ikuti arahan koordinator dan petugas berwenang."),
      h("p", { style: "margin-top:8px" }, h("a", { href: "#alerts", style: "color:#fff;font-weight:700" }, "Baca pesan lengkap →"))
    ));
  } else {
    box.append(h("div", { class: "hero" },
      h("small", {}, "Kondisi wilayah"),
      h("h1", {}, "Tidak ada peringatan aktif"),
      h("p", {}, "Tetap saling jaga. Laporkan bila melihat air sungai naik atau luapan banjir.")
    ));
  }

  box.append(
    h("div", { class: "card", style: "display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:linear-gradient(90deg,#eef7ff,#f2fcf8);border-color:#b9e2fe;margin-bottom:14px;cursor:pointer", onclick: () => { location.hash = "#live"; } },
      h("div", { style: "display:flex;align-items:center;gap:10px" },
        h("span", { class: "pulse-badge", style: "background:#e0f2fe;color:#0369a1;border-color:#7dd3fc" }, "🌊 LIVE SUNGAI & CUACA"),
        h("span", { style: "font-size:13.5px;font-weight:700;color:var(--navy)" }, "Pantau ketinggian air sungai & cuaca Bandung →")
      ),
      h("button", { class: "small sec", style: "padding:4px 10px;font-size:12px" }, "Buka Live")
    )
  );

  const statusExplain = {
    belum_terkonfirmasi: "Belum ada kabar dari Anda untuk kejadian ini.",
    aman_mandiri: "Tercatat dari laporan Anda. Petugas belum memverifikasi di lapangan.",
    butuh_bantuan: "Permintaan Anda sudah masuk antrean koordinator.",
    dalam_penanganan: "Bantuan sedang menuju / menangani Anda.",
    tiba_di_titik_aman: "Anda tercatat sudah tiba di titik aman.",
  };
  box.append(h("div", { class: "card accent" },
    h("div", { class: "row", style: "align-items:center" },
      h("div", {}, h("div", { class: "muted small-text" }, "Status keselamatan saya"),
        h("b", { style: "font-size:18px" }, lab(res.latest_status)), res.latest_status_at ? h("span", { class: "muted small-text" }, " · " + fmt(res.latest_status_at)) : null,
        h("div", { class: "muted small-text" }, statusExplain[res.latest_status] || "")),
      h("button", { class: "sec small", onclick: act(async () => { const p = await getPosition(); await postOrQueue("/me/location", { lat: p[0], lng: p[1] }, "Bagikan lokasi"); }, "Lokasi terkini dibagikan ke koordinator") }, "Bagikan lokasi saya"))));

  const help = h("div", { class: "card", hidden: true });
  const sendStatus = async (body, share) => {
    if (share) { try { const p = await getPosition(7000); body.lat = p[0]; body.lng = p[1]; } catch (e) { toast(e.message + " — status tetap dikirim tanpa lokasi", true); } }
    const r = await postOrQueue("/me/status", body, body.status === "aman" ? "Saya Aman" : "Butuh Bantuan");
    if (r.sent) { toast(body.status === "aman" ? "Terima kasih, status aman terkirim" : "Permintaan bantuan terkirim ke koordinator"); await reload(); }
  };
  let need = "evakuasi";
  const shareLoc = h("input", { type: "checkbox", checked: true });
  const note = h("textarea", { placeholder: "Contoh: ada lansia di rumah, air sudah selutut" });
  const needBtns = [["evakuasi", "Evakuasi / jemput"], ["medis", "Medis"], ["logistik", "Makanan / air"], ["lainnya", "Lainnya"]]
    .map(([v, t]) => h("button", { type: "button", class: v === need ? "on" : "", onclick: ev => { need = v; needBtns.forEach(b => b.classList.toggle("on", b === ev.currentTarget)); } }, t));
  help.append(h("h3", {}, "Saya butuh bantuan"), h("div", { class: "choice" }, needBtns), field("Keterangan (opsional)", note),
    h("label", { class: "chk" }, shareLoc, "Bagikan lokasi saya ke koordinator (hanya koordinator wilayah & relawan yang ditugaskan)"),
    h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(() => sendStatus({ status: "butuh_bantuan", need_type: need, note: note.value.trim() || null }, shareLoc.checked)) }, "Kirim permintaan bantuan"),
      h("button", { class: "ghost", onclick: () => { help.hidden = true; } }, "Batal")));

  box.append(h("div", { class: "bigbtns" },
    h("button", { class: "big safe", onclick: act(() => sendStatus({ status: "aman" }, false)) }, icon("check"), "SAYA AMAN", h("small", {}, "Kabari koordinator bahwa Anda selamat")),
    h("button", { class: "big help", onclick: () => { help.hidden = false; help.scrollIntoView({ behavior: "smooth" }); } }, icon("sos"), "BUTUH BANTUAN", h("small", {}, "Minta evakuasi, medis, atau logistik")),
    h("button", { class: "big report wide", onclick: () => { location.hash = "#lapor"; } }, icon("lapor"), "LAPOR KEJADIAN BANJIR", h("small", {}, "Air sungai naik, luapan, atau genangan air"))), help);

  const from = res.last_lat != null ? [res.last_lat, res.last_lng] : res.home_lat != null ? [res.home_lat, res.home_lng] : null;
  const usable = shelters.filter(s => s.is_verified && ["tersedia", "terbatas"].includes(s.status));
  const near = from ? usable.map(s => ({ s, d: dist(from, [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0] : usable[0] && { s: usable[0], d: null };
  box.append(h("div", { class: "card" }, h("h3", {}, "Titik aman terdekat"),
    near ? [h("div", { style: "font-size:18px;font-weight:800;color:var(--navy)" }, near.s.name),
      h("div", { class: "muted" }, `${near.s.address} · ${lab(near.s.status)} · terisi ${near.s.occupancy || 0}/${near.s.capacity ?? "?"}${near.d != null ? " · ±" + fmtDist(near.d) + " garis lurus dari " + (res.last_lat != null ? "lokasi terkini" : "rumah") : ""}`),
      h("div", { class: "btns", style: "margin-top:12px" }, h("button", { class: "teal", onclick: () => { location.hash = "#peta"; } }, "Rute & navigasi ke shelter"),
        h("a", { href: gmaps(near.s.lat, near.s.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec", type: "button" }, "Buka di Google Maps")))]
      : h("p", { class: "muted" }, "Belum ada shelter terverifikasi di wilayah Anda.")));
}

// ---------- Lapor kejadian ----------
async function viewReport(box, ctx) {
  if (me.role === "pos_pantau") {
    box.append(
      h("h2", {}, "Laporan & Verifikasi Pos Pantau"),
      h("div", { class: "notice ok", style: "font-size:14.5px;line-height:1.6;padding:16px" },
        "Petugas Pos Pantau tidak melakukan pelaporan kejadian warga. Tugas Pos Pantau adalah memantau kondisi sungai dan cuaca secara real-time, serta memverifikasi laporan kejadian yang masuk dari masyarakat."
      ),
      h("div", { style: "margin-top:16px" },
        h("button", { class: "teal", onclick: () => { location.hash = "#reports"; } }, "📥 Buka Menu Laporan & Verifikasi Warga")
      )
    );
    return;
  }

  const regions = await api("GET", "/regions/lookup");
  const title = h("input", { placeholder: "Contoh: Luapan Sungai Cikapundung Gandok / Tanggul Jebol", required: true });

  const RIVER_CONDITIONS = [
    { id: "air_naik", label: "Air sungai naik / meluap" },
    { id: "sampah_menumpuk", label: "Sampah menumpuk / menyumbat" },
    { id: "arus_deras", label: "Arus air sangat deras" },
    { id: "tanggul_rusak", label: "Tanggul retak / jebol" },
    { id: "genangan_jalan", label: "Genangan jalan / akses terputus" },
    { id: "masuk_rumah", label: "Air masuk ke permukiman / rumah" },
    { id: "lumpur_pekat", label: "Lumpur pekat / material hanyut" }
  ];

  const condBoxes = RIVER_CONDITIONS.map(opt => {
    const chk = h("input", { type: "checkbox", value: opt.id });
    const lbl = h("label", {
      style: "display:inline-flex;align-items:center;gap:6px;background:#f8fafc;padding:6px 12px;border:1px solid #cbd5e1;border-radius:8px;cursor:pointer;font-size:13px;user-select:none;transition:all .15s"
    }, chk, opt.label);
    chk.onchange = () => {
      lbl.style.background = chk.checked ? "#e0f2fe" : "#f8fafc";
      lbl.style.borderColor = chk.checked ? "#0284c7" : "#cbd5e1";
      lbl.style.color = chk.checked ? "#0369a1" : "inherit";
      lbl.style.fontWeight = chk.checked ? "700" : "normal";
    };
    return { opt, chk, lbl };
  });

  const condContainer = h("div", {
    style: "display:flex;flex-wrap:wrap;gap:8px;margin-top:4px"
  }, condBoxes.map(c => c.lbl));

  const desc = h("textarea", { placeholder: "Deskripsi tambahan atau keterangan detail kejadian di lapangan (min. 5 karakter)" });
  const lat = h("input", { type: "number", step: "any", placeholder: "lat" });
  const lng = h("input", { type: "number", step: "any", placeholder: "lng" });
  let gps = null, pin = null, map = null;
  const put = (la, ln) => {
    lat.value = (+la).toFixed(6); lng.value = (+ln).toFixed(6);
    if (map) { pin ? pin.setLatLng([la, ln]) : (pin = L.marker([la, ln], { icon: pinIcon("#dc2626", "!") }).addTo(map)); map.panTo([la, ln]); }
  };

  const BANDUNG_POS_PANTAU_PLACES = [
    { id: "custom", name: "Ketik Lokasi Sendiri / Alamat Lainnya", lat: null, lng: null, region_hint: null },
    { id: "gandok", name: "Pos Pantau Cikapundung Gandok (Cidadap)", lat: -6.8794, lng: 107.6083, region_hint: "Cidadap" },
    { id: "viaduct", name: "Pos Pantau Cikapundung Viaduct (Sumur Bandung)", lat: -6.9147, lng: 107.6098, region_hint: "Sumur Bandung" },
    { id: "pagarsih", name: "Pos Pantau Citepus Pagarsih (Astana Anyar)", lat: -6.9242, lng: 107.5956, region_hint: "Astana Anyar" },
    { id: "rancacili", name: "Pos Pantau Cidurian Rancacili (Rancasari)", lat: -6.9531, lng: 107.6689, region_hint: "Rancasari" },
    { id: "rajawali", name: "Pos Pantau Cibeureum Rajawali (Andir)", lat: -6.9089, lng: 107.5756, region_hint: "Andir" },
    { id: "gedebage", name: "Pos Pantau Cinambo Gedebage (Gedebage)", lat: -6.9489, lng: 107.6972, region_hint: "Gedebage" }
  ];

  const locStationSel = h("select", {},
    BANDUNG_POS_PANTAU_PLACES.map(p => h("option", { value: p.id }, p.name))
  );

  const locCustomInput = h("input", {
    placeholder: "Ketik nama tempat/jalan kejadian (mis. Jl. Pagarsih No. 12 / bantaran sungai)",
    value: ""
  });

  locStationSel.onchange = () => {
    const sel = BANDUNG_POS_PANTAU_PLACES.find(p => p.id === locStationSel.value);
    if (!sel || sel.id === "custom") {
      locCustomInput.focus();
      return;
    }
    locCustomInput.value = sel.name;
    gps = null;
    put(sel.lat, sel.lng);
  };

  const sim = h("input", { type: "checkbox" });
  const sensor = h("input", { type: "checkbox" });
  const photo = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
  const out = h("div");

  const submit = act(async () => {
    const selectedConds = condBoxes.filter(c => c.chk.checked).map(c => c.opt.id);
    const condLabels = condBoxes.filter(c => c.chk.checked).map(c => c.opt.label.trim());
    const locName = locCustomInput.value.trim() || (locStationSel.value !== "custom" ? (BANDUNG_POS_PANTAU_PLACES.find(p => p.id === locStationSel.value)?.name || "") : "");
    const reportTitle = title.value.trim() || (condLabels.length ? `Laporan: ${condLabels.slice(0, 2).join(", ")}` : "Laporan Banjir");
    const locPrefix = locName ? `[Lokasi: ${locName}] ` : "";
    const condText = condLabels.length ? `[Kondisi: ${condLabels.join(", ")}] ` : "";
    const detailText = desc.value.trim();
    const fullDesc = `${locPrefix}${condText}${detailText}`.trim() || `${reportTitle} di ${locName || 'Kota Bandung'}.`;

    let targetRegionId = me.region_id;
    const selStation = BANDUNG_POS_PANTAU_PLACES.find(p => p.id === locStationSel.value);
    if (selStation && selStation.region_hint && regions && regions.length) {
      const matched = regions.find(r => r.name.toLowerCase().includes(selStation.region_hint.toLowerCase()));
      if (matched) targetRegionId = matched.id;
    }
    if (!targetRegionId && regions && regions.length) {
      targetRegionId = regions[0].id;
    }

    const body = {
      hazard: "banjir",
      title: reportTitle,
      location_name: locName || reportTitle,
      conditions: selectedConds,
      description: fullDesc.length >= 5 ? fullDesc : `${reportTitle} - Banjir Kota Bandung.`,
      region_id: targetRegionId,
      lat: num(lat.value),
      lng: num(lng.value),
      source_mode: sim.checked ? "simulation" : "real",
      reported_at: new Date().toISOString(),
      client_ref: uid(),
    };
    if (gps) { body.gps_lat = gps[0]; body.gps_lng = gps[1]; }
    if (me.role === "pos_pantau" && sensor.checked) body.from_sensor = true;
    if (body.lat == null || body.lng == null) throw new Error("Pilih lokasi di peta, pakai GPS, atau isi koordinat");
    if (body.description.length < 5) throw new Error("Deskripsi minimal 5 karakter");

    const r = await postOrQueue("/reports", body, `Laporan ${reportTitle}`);
    if (!r.sent) { out.replaceChildren(h("div", { class: "notice warn" }, "Laporan disimpan di perangkat dan akan dikirim saat online. Foto hanya bisa dikirim saat online.")); return; }
    let msg = `Laporan #${r.data.id} "${reportTitle}" diterima — status: ${lab(r.data.status)}${r.data.incident_id ? `, kejadian #${r.data.incident_id}` : ""}.`;
    if (photo.files[0]) {
      const fd = new FormData(); fd.append("file", photo.files[0]);
      try { await api("POST", `/reports/${r.data.id}/photo`, fd); msg += " Foto terlampir."; }
      catch (e) { msg += " Foto gagal: " + e.message; }
    }
    out.replaceChildren(h("div", { class: "notice ok" }, msg));
    title.value = "";
    desc.value = "";
    photo.value = "";
    locStationSel.value = "custom";
    locCustomInput.value = "";
    condBoxes.forEach(c => { c.chk.checked = false; c.chk.onchange(); });
  });

  box.append(h("h2", {}, "Lapor Kejadian Banjir"),
    h("div", { class: "notice" }, "Pilih pos pantau atau ketik nama lokasi kejadian luapan banjir. Jangan mendekati arus deras demi foto."),
    h("div", { class: "cols-2" },
      h("div", { class: "card" },
        field("Judul Laporan", title),
        field("Kondisi Laporan / Kondisi Sungai (Bisa pilih lebih dari 1)", condContainer),
        field("Pilihan Lokasi Sesuai Pos Pantau / Ketik Sendiri", locStationSel),
        field("Nama Tempat / Detail Alamat Kejadian", locCustomInput),
        field("Deskripsi Detail / Catatan Lapangan", desc),
        h("div", { class: "row", style: "align-items:flex-end;gap:8px" },
          field("Latitude", lat),
          field("Longitude", lng),
          h("button", {
            class: "sec", type: "button", style: "margin-bottom:6px;white-space:nowrap",
            onclick: act(async () => { const p = await getPosition(); gps = [p[0], p[1]]; put(p[0], p[1]); }, "Lokasi GPS dipakai"),
          }, "📍 Pakai GPS saya")
        ),
        field("Foto (opsional, JPG/PNG/WebP, maks. 5 MB)", photo),
        h("label", { class: "chk" }, sim, "Data simulasi (demo) — diberi label SIMULASI"),
        me.role === "pos_pantau" ? h("label", { class: "chk" }, sensor, "Ini indikasi dari sensor pos pantau") : null,
        h("button", { onclick: submit, style: "width:100%;margin-top:6px" }, "Kirim laporan"), out),
      h("div", { class: "card" }, h("h3", {}, "Ketuk peta untuk menaruh pin lokasi"), h("div", { id: "mapslot", class: "map tall" }))));
  ctx.post(() => {
    map = newMap($("#mapslot"));
    if (map) map.on("click", e => { gps = null; put(e.latlng.lat, e.latlng.lng); });
  });
}

// ---------- Laporan saya ----------
async function viewMine(box) {
  const rows = await api("GET", "/reports/mine");
  const queued = store.get(QKEY, []).filter(i => i.user === me.id);
  const showPhoto = async (r, cell) => {
    const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
    cell.replaceChildren(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto laporan" }));
  };
  box.append(h("h2", {}, "Laporan Saya"));
  if (queued.length) box.append(h("div", { class: "card" }, h("h3", {}, "Menunggu dikirim (tersimpan di perangkat)"),
    table([{ label: "Jenis", key: "label" }, { label: "Disimpan", render: q => fmt(q.at) }], queued),
    h("button", { class: "small", onclick: act(async () => { await flushQueue(); await reload(); }) }, "Kirim sekarang")));
  box.append(h("div", { class: "card" }, table([
    { label: "#", key: "id" },
    { label: "Laporan", render: r => [
      h("b", { style: "color:var(--navy)" }, r.title || "Laporan Banjir"), " ", simBadge(r.source_mode === "simulation"),
      r.conditions && r.conditions.length ? h("div", { style: "display:flex;flex-wrap:wrap;gap:4px;margin:4px 0" }, r.conditions.map(c => badge(lab(c), "b-warn"))) : null,
      h("div", { class: "small-text", style: "margin-top:2px" }, r.description)
    ] },
    { label: "Status", render: r => badge(lab(r.status), r.status === "terverifikasi" ? "b-ok" : r.status === "ditolak" ? "b-bad" : "b-info") },
    { label: "Catatan koordinator", render: r => r.status_reason || "-" },
    { label: "Kejadian", render: r => r.incident_id ? "#" + r.incident_id : "-" },
    { label: "Dikirim", render: r => fmt(r.received_at) },
    { label: "Foto", render: r => { const c = h("span"); if (r.has_photo) c.append(h("button", { class: "sec small", onclick: act(() => showPhoto(r, c)) }, "Lihat")); else c.append("-"); return c; } },
  ], rows, "Anda belum mengirim laporan.")));
}

// ---------- Peta evakuasi & navigasi ----------
async function viewMapNav(box, ctx) {
  const isSar = ["tim_sar", "relawan", "petugas", "koordinator"].includes(me.role);
  const activeOrder = store.get("rw_active_task_nav");
  const [shelters, routes, hazards, res, rescueData, helpReqs, sarTasks] = await Promise.all([
    api("GET", "/shelters"), api("GET", "/evacuation-routes"), api("GET", "/road-conditions"),
    api("GET", "/me/resident").catch(() => null),
    isSar ? api("GET", "/evacuation/rescue-targets").catch(() => null) : null,
    isSar ? api("GET", "/help-requests").catch(() => []) : [],
    isSar ? api("GET", "/tasks").catch(() => []) : []
  ]);
  let map = null, meMarker = null, accCircle = null, myPos = null, routeLayer = null, watchId = null, chosen = null;
  const status = h("div", { class: "muted small-text" }, "Posisi belum ditentukan.");
  const results = h("div"), navBox = h("div");
  const setPos = (p, why) => {
    myPos = [p[0], p[1]];
    status.textContent = `Posisi: ${why} (${p[0].toFixed(5)}, ${p[1].toFixed(5)})${p[2] ? " · akurasi ±" + Math.round(p[2]) + " m" : ""}`;
    if (!map) return;
    meMarker ? meMarker.setLatLng(myPos) : (meMarker = L.marker(myPos, { icon: meIcon(), zIndexOffset: 1000 }).addTo(map).bindTooltip(tip("Posisi saya")));
    if (p[2]) { accCircle ? accCircle.setLatLng(myPos).setRadius(p[2]) : (accCircle = L.circle(myPos, { radius: p[2], color: "#0a64b8", weight: 1, fillOpacity: .08 }).addTo(map)); }
  };
  const usable = shelters.filter(s => s.is_verified && ["tersedia", "terbatas"].includes(s.status));

  function drawOption(o, fromCache) {
    chosen = o;
    if (routeLayer) routeLayer.remove();
    if (map) { routeLayer = L.polyline(o.points, { color: "#0a64b8", weight: 7, opacity: .85 }).addTo(map); map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] }); }
    [...results.querySelectorAll(".route-opt")].forEach(el => el.classList.toggle("on", el.dataset.sid === String(o.shelter.id)));
    navBox.replaceChildren(h("div", { class: "card" },
      h("h3", {}, `Ke ${o.shelter.name}`),
      h("div", { class: "btns", style: "margin-bottom:10px" },
        badge(o.label, o.source === "osrm" ? "b-warn" : "b-bad"), fromCache ? badge("RUTE TERSIMPAN (OFFLINE)", "b-sim") : null),
      o.warnings.map(w => h("div", { class: "notice bad" }, "⚠ " + w)),
      h("p", {}, h("b", {}, fmtDist(o.distance_m)), " · ±", fmtDur(o.duration_s), " jalan kaki"),
      h("ol", { class: "turns" }, o.steps.map(s => h("li", {}, s))),
      h("div", { class: "btns", style: "margin-top:12px" },
        h("button", { class: "teal", onclick: startNav }, "Mulai navigasi"),
        h("a", { href: gmaps(o.shelter.lat, o.shelter.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec", type: "button" }, "Google Maps"))),
      h("div", { id: "navlive" })));
  }
  function renderOptions(data, fromCache) {
    results.replaceChildren(h("div", {},
      fromCache ? h("div", { class: "notice warn" }, `Offline: menampilkan rute yang dihitung ${fmt(fromCache)}. Kondisi jalan bisa sudah berubah — utamakan rute resmi & arahan petugas.`) : null,
      h("div", { class: "notice" }, data.note),
      data.options.length ? data.options.map(o => h("div", { class: "route-opt", "data-sid": o.shelter.id, onclick: () => drawOption(o, fromCache) },
        h("b", {}, o.shelter.name), " ", o.warnings.length ? badge(`${o.warnings.length} peringatan`, "b-bad") : badge("tanpa titik bahaya tercatat", "b-ok"),
        h("div", { class: "muted small-text" }, `${fmtDist(o.distance_m)} · ±${fmtDur(o.duration_s)} · ${o.source === "osrm" ? "rute jalan" : "garis lurus"}`)))
        : h("p", { class: "muted" }, "Tidak ada shelter terverifikasi yang tersedia.")));
    if (data.options[0]) drawOption(data.options[0], fromCache);
  }
  const findRoute = act(async () => {
    if (!myPos) {
      try { setPos(await getPosition(), "GPS"); }
      catch (e) {
        if (res?.home_lat != null) { setPos([res.home_lat, res.home_lng], "lokasi rumah"); toast(e.message + " — memakai lokasi rumah", true); }
        else throw new Error(e.message + ". Ketuk peta untuk menentukan posisi.");
      }
    }
    try {
      const data = await api("GET", `/routing/shelter?lat=${myPos[0]}&lng=${myPos[1]}`);
      store.set("rw_last_route", { at: new Date().toISOString(), data });
      renderOptions(data, null);
    } catch (e) {
      if (!e.offline) throw e;
      const saved = store.get("rw_last_route");
      if (saved) renderOptions(saved.data, saved.at);
      else compassOnly();
    }
  });

  const navigateToTarget = (lat, lng, name, victim = null) => {
    if (!myPos) {
      if (res?.home_lat != null) setPos([res.home_lat, res.home_lng], "lokasi awal");
      else setPos(DEMO_CENTER, "Kota Bandung");
    }
    const d = dist(myPos, [lat, lng]);
    const nearShelter = usable.map(s => ({ s, d: dist([lat, lng], [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0]?.s;
    const durSec = Math.round(d / 1.2);
    drawOption({
      shelter: { name: `Warga: ${name}`, lat, lng, id: 9999 },
      points: [myPos, [lat, lng]],
      distance_m: d,
      duration_s: durSec,
      source: "garis_lurus",
      label: "Rute Penyelamatan Tim SAR",
      warnings: ["Utamakan keselamatan tim saat evakuasi."],
      steps: [
        `Menuju lokasi ${name} di koordinat ${lat.toFixed(5)}, ${lng.toFixed(5)} (jarak: ±${fmtDist(d)})`,
        nearShelter ? `Setelah menjemput korban, arahkan evakuasi ke shelter terdekat: ${nearShelter.name} (${nearShelter.address || 'Bandung'}) — ±${fmtDist(dist([lat, lng], [nearShelter.lat, nearShelter.lng]))}` : "Bawa korban ke shelter aman terdekat."
      ]
    }, null);
    if (map) map.setView([lat, lng], 17);
  };

  function compassOnly() {
    const near = usable.map(s => ({ s, d: dist(myPos, [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0];
    if (!near) return results.replaceChildren(h("div", { class: "notice bad" }, "Offline dan belum ada data shelter tersimpan."));
    results.replaceChildren(h("div", { class: "notice warn" }, "Offline & belum ada rute tersimpan: pakai arah kompas ke shelter terdekat dan rute resmi di peta."));
    drawOption({ shelter: near.s, points: [myPos, [near.s.lat, near.s.lng]], distance_m: near.d, duration_s: near.d / 1.2, source: "garis_lurus",
      label: "Garis lurus (offline) — hanya petunjuk arah", warnings: [], steps: [`Menuju ${compass(bearing(myPos, [near.s.lat, near.s.lng]))} sejauh ±${fmtDist(near.d)}`] }, new Date().toISOString());
  }
  function navUpdate(p) {
    setPos(p, "GPS langsung");
    const live = $("#navlive"); if (!live || !chosen) return;
    const dest = [chosen.shelter.lat, chosen.shelter.lng];
    const d = dist(myPos, dest), b = bearing(myPos, dest), off = distToLine(myPos, chosen.points);
    const arrow = h("div", { class: "arrow", style: `transform:rotate(${b}deg)` }, icon("arrow"));
    live.replaceChildren(h("div", { class: "card flat", style: "margin:12px 0 0;background:var(--soft)" },
      h("div", { class: "navpanel" }, arrow, h("div", {},
        h("div", { style: "font-size:20px;font-weight:800;color:var(--navy)" }, d < 30 ? "Anda sudah di titik tujuan" : `±${fmtDist(d)} lagi`),
        h("div", { class: "muted" }, `Arah ${Math.round(b)}° (${compass(b)}) dari utara · akurasi GPS ±${Math.round(p[2] || 0)} m`),
        off > 50 ? h("div", { class: "err", style: "font-weight:700" }, `Anda ±${fmtDist(off)} di luar garis rute`) : null,
        d < 30 ? h("div", { style: "font-weight:700;color:var(--ok)" }, "Tiba di tujuan.") : null)),
      h("button", { class: "danger small", style: "margin-top:10px", onclick: stopNav }, "Hentikan navigasi")));
    if (map) map.panTo(myPos);
  }
  function startNav() {
    if (!navigator.geolocation) return toast("GPS tidak tersedia", true);
    stopNav();
    watchId = navigator.geolocation.watchPosition(pos => navUpdate([pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy]),
      () => toast("GPS tidak didapat. Pastikan izin lokasi aktif.", true), { enableHighAccuracy: true, maximumAge: 4000, timeout: 15000 });
    toast("Navigasi dimulai — layar mengikuti posisi Anda");
  }
  function stopNav() { if (watchId != null) navigator.geolocation.clearWatch(watchId); watchId = null; }
  cleanups.push(stopNav);

  const legendItems = [
    ["#0f9d6b", "Shelter Terverifikasi"],
    ["#b91c1c", "Titik Bahaya Jalan"],
    ["#0f9d6b", "Rute Resmi Hijau"],
    ["#0a64b8", "Posisi Saya"]
  ];
  if (isSar) {
    legendItems.push(["#dc2626", "Warga Prioritas (Lansia/Balita/Sakit/Hamil)"]);
    legendItems.push(["#eab308", "Warga Butuh Evakuasi"]);
    legendItems.push(["#2563eb", "Target Penugasan Tim SAR"]);
  }

  // Gabungkan seluruh target warga yang membutuhkan bantuan / penugasan SAR
  const targetMap = new Map();
  if (rescueData && rescueData.items) {
    rescueData.items.forEach(t => {
      const key = t.resident_id || t.name;
      targetMap.set(key, { ...t });
    });
  }
  if (helpReqs && helpReqs.length) {
    helpReqs.forEach(hr => {
      const r = hr.resident;
      if (!r) return;
      const key = r.id || r.name;
      const existing = targetMap.get(key) || {};
      const isVuln = hr.is_vulnerable || (r.vulnerability && r.vulnerability.length > 0);
      targetMap.set(key, {
        ...existing,
        resident_id: r.id,
        name: r.name,
        status: "butuh_bantuan",
        vulnerability: r.vulnerability || [],
        family_vulnerability: hr.family_vulnerability || [],
        priority: isVuln ? "kritis" : "sedang",
        lat: existing.lat ?? r.last_lat ?? r.home_lat,
        lng: existing.lng ?? r.last_lng ?? r.home_lng,
        score: isVuln ? 90 : 40,
        note: hr.note
      });
    });
  }
  if (sarTasks && sarTasks.length) {
    sarTasks.forEach(t => {
      if (["selesai", "gagal", "dibatalkan"].includes(t.status)) return;
      const key = t.resident_id || t.resident_name || `task_${t.id}`;
      const existing = targetMap.get(key) || {};
      const isVuln = (t.resident_vulnerability && t.resident_vulnerability.length > 0) || ["kritis", "tinggi"].includes(t.priority);
      targetMap.set(key, {
        ...existing,
        resident_id: t.resident_id,
        name: t.resident_name || existing.name || `Warga Tugas #${t.id}`,
        status: t.status === "baru" ? "butuh_bantuan" : "dalam_penanganan",
        vulnerability: t.resident_vulnerability || existing.vulnerability || [],
        priority: t.priority || (isVuln ? "kritis" : "sedang"),
        lat: t.lat ?? existing.lat,
        lng: t.lng ?? existing.lng,
        score: isVuln ? 95 : 50,
        task: t
      });
    });
  }
  const allVictims = Array.from(targetMap.values());

  const activeOrderBanner = activeOrder ? h("div", {
    class: "card",
    style: "background:linear-gradient(135deg,#eff6ff,#dbeafe);border:2px solid #2563eb;margin-bottom:12px;box-shadow:0 4px 14px rgba(37,99,235,.2)"
  },
    h("div", { style: "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px" },
      h("div", {},
        h("div", { style: "color:#1d4ed8;font-weight:800;font-size:15px;display:flex;align-items:center;gap:6px" },
          "🎯 PERINTAH PENUGASAN EVAKUASI TIM SAR"
        ),
        h("div", { style: "font-size:14px;color:var(--navy);font-weight:700;margin-top:2px" },
          `Target: ${activeOrder.name || 'Warga'} · Prioritas: ${(activeOrder.priority || 'Tinggi').toUpperCase()}`
        ),
        activeOrder.vulnerability && activeOrder.vulnerability.length ? h("div", { style: "font-size:12px;color:#dc2626;font-weight:700;margin-top:2px" },
          "Kerentanan: " + activeOrder.vulnerability.join(", ")
        ) : null
      ),
      h("div", { class: "btns" },
        activeOrder.lat != null ? h("button", {
          class: "green small",
          style: "font-weight:700",
          onclick: () => navigateToTarget(activeOrder.lat, activeOrder.lng, activeOrder.name)
        }, "🎯 Mulai Arahkan ke Target") : null,
        h("button", {
          class: "ghost small",
          style: "color:#dc2626;border-color:#fca5a5",
          onclick: () => { store.del("rw_active_task_nav"); reload(); }
        }, "✕ Selesai / Batal")
      )
    )
  ) : null;

  const sarTargetsBox = h("div");
  if (isSar && allVictims.length) {
    sarTargetsBox.append(
      h("div", { class: "card", style: "background:linear-gradient(135deg,#fff1f2,#fef2f2);border:1px solid #fecdd3;margin-top:14px" },
        h("h3", { style: "margin:0 0 8px;color:#991b1b;font-size:16px" }, `🎯 Target Penyelamatan Warga (${allVictims.length})`),
        h("p", { class: "muted small-text" }, "Warga yang membutuhkan bantuan / penugasan evakuasi (Warna Merah: Prioritas Lansia/Balita/Sakit/Hamil, Kuning: Bantuan Evakuasi):"),
        allVictims.map(t => {
          const isVulnerable = (t.vulnerability && t.vulnerability.length > 0) ||
                               (t.family_vulnerability && t.family_vulnerability.length > 0) ||
                               t.priority === "kritis" || t.priority === "tinggi";
          const isAssigned = activeOrder && (
            (activeOrder.resident_id && activeOrder.resident_id === t.resident_id) ||
            (activeOrder.name && t.name && activeOrder.name.toLowerCase() === t.name.toLowerCase())
          );
          return h("div", {
            style: `display:flex;justify-content:space-between;align-items:center;background:#fff;padding:8px 12px;border-radius:8px;margin-bottom:6px;border:1px solid ${isAssigned ? '#2563eb' : isVulnerable ? '#fca5a5' : '#fed7aa'};box-shadow:${isAssigned ? '0 0 8px rgba(37,99,235,.25)' : 'none'};gap:8px`
          },
            h("div", {},
              isAssigned ? badge("🎯 TUGAS ANDA", "b-ok") : null,
              h("b", { style: "color:var(--navy);font-size:14px" }, t.name), " ",
              isVulnerable ? badge("PRIORITAS RENTAN", "b-bad") : badge("BUTUH EVAKUASI", "b-warn"),
              t.vulnerability && t.vulnerability.length ? h("div", { style: "font-size:12px;color:#dc2626;font-weight:700" }, "Kerentanan: " + t.vulnerability.join(", ")) : null,
              t.lat != null ? h("div", { class: "muted small-text" }, `Lokasi: ${t.lat.toFixed(5)}, ${t.lng.toFixed(5)}`) : h("div", { class: "muted small-text" }, "Lokasi rumah belum terdata")
            ),
            t.lat != null ? h("button", {
              class: isAssigned ? "green small" : "teal small",
              style: isAssigned ? "font-weight:700" : "",
              onclick: () => navigateToTarget(t.lat, t.lng, t.name, t)
            }, isAssigned ? "🎯 Navigasi" : "📍 Arahkan") : null
          );
        })
      )
    );
  }

  box.append(h("h2", {}, isSar ? "Peta Evakuasi & Penyelamatan Tim SAR" : "Peta Evakuasi"));
  if (activeOrderBanner) box.append(activeOrderBanner);
  box.append(h("div", { class: "cols-2" },
    h("div", { class: "card" },
      legend(legendItems),
      h("div", { id: "navmap", class: "map tall" }),
      h("p", { class: "muted small-text" }, "Peta dan titik shelter Bandung tersimpan otomatis secara offline. Gunakan rute resmi dan utamakan keselamatan.")),
    h("div", {},
      isSar ? sarTargetsBox : null,
      h("div", { class: "card" }, h("h3", {}, isSar ? "Navigasi & Pencarian Rute" : "Cari rute ke shelter"), status,
        h("div", { class: "btns", style: "margin:10px 0" },
          h("button", { class: "sec", onclick: act(async () => { setPos(await getPosition(), "GPS"); }) }, "Pakai GPS"),
          res?.home_lat != null ? h("button", { class: "sec", onclick: () => setPos([res.home_lat, res.home_lng], "lokasi rumah") }, "Dari rumah") : null,
          h("button", { onclick: findRoute }, "Cari shelter terdekat")),
        h("p", { class: "muted small-text" }, "Atau ketuk peta untuk menentukan posisi awal navigasi."), results),
      navBox,
      !isSar ? sarTargetsBox : null)));

  ctx.post(() => {
    map = newMap($("#navmap"));
    if (!map) return;
    addRoutes(map, routes); addHazards(map, hazards); addShelters(map, shelters);

    // Plot warga yang butuh bantuan / belum terkonfirmasi untuk Tim SAR & Koordinator
    if (isSar && allVictims.length) {
      allVictims.forEach(victim => {
        if (victim.lat == null || victim.lng == null) return;
        const isVulnerable = (victim.vulnerability && victim.vulnerability.length > 0) ||
                             (victim.family_vulnerability && victim.family_vulnerability.length > 0) ||
                             victim.priority === "kritis" || victim.priority === "tinggi";

        const isAssignedOrder = activeOrder && (
          (activeOrder.resident_id && activeOrder.resident_id === victim.resident_id) ||
          (activeOrder.name && victim.name && activeOrder.name.toLowerCase() === victim.name.toLowerCase()) ||
          (activeOrder.lat != null && Math.abs(activeOrder.lat - victim.lat) < 0.0001 && Math.abs(activeOrder.lng - victim.lng) < 0.0001)
        );

        let pinColor = "#eab308"; // Kuning default untuk warga butuh evakuasi
        let pinIconChar = "SOS";
        let pulse = false;

        if (isAssignedOrder) {
          pinColor = "#2563eb"; // Biru Target Tugas
          pinIconChar = "🎯";
          pulse = true;
        } else if (isVulnerable) {
          pinColor = "#dc2626"; // Titik Merah untuk Prioritas
          pinIconChar = "!";
          pulse = true;
        } else {
          pinColor = "#eab308"; // Warna Kuning untuk Warga yang Perlu Dievakuasi
          pinIconChar = "SOS";
          pulse = false;
        }

        const m = L.marker([victim.lat, victim.lng], {
          icon: pinIcon(pinColor, pinIconChar, pulse),
          zIndexOffset: isAssignedOrder ? 2000 : isVulnerable ? 1500 : 1000
        }).addTo(map);

        const nearShelter = usable.map(s => ({ s, d: dist([victim.lat, victim.lng], [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0]?.s;

        const pop = h("div", { style: "min-width:230px" },
          isAssignedOrder ? badge("🎯 TARGET PERINTAH EVAKUASI ANDA", "b-ok") : null,
          h("b", { style: "font-size:15px;color:var(--navy);display:block;margin:4px 0" }, victim.name),
          h("div", { style: "display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px" },
            isVulnerable ? badge("PRIORITAS RENTAN", "b-bad") : badge("WARGA BUTUH EVAKUASI", "b-warn"),
            badge(lab(victim.status), "b-info")
          ),
          h("div", { class: "muted small-text", style: "margin:4px 0" }, `Prioritas: ${(victim.priority || 'sedang').toUpperCase()}${victim.score ? ` (${victim.score} poin)` : ''}`),
          victim.vulnerability && victim.vulnerability.length ? h("div", { style: "font-size:12px;color:#dc2626;font-weight:700;margin-bottom:6px" }, "Kerentanan: " + victim.vulnerability.join(", ")) : null,
          nearShelter ? h("div", { style: "font-size:12px;color:#0f9d6b;margin-bottom:8px;font-weight:600" }, `🏥 Shelter terdekat: ${nearShelter.name}`) : null,
          h("div", { class: "btns" },
            h("button", {
              class: "teal small",
              onclick: () => navigateToTarget(victim.lat, victim.lng, victim.name, victim)
            }, "📍 Arahkan Navigasi ke Korban"),
            h("a", { href: gmaps(victim.lat, victim.lng), target: "_blank", rel: "noopener" },
              h("button", { class: "sec small", type: "button" }, "Google Maps ↗")
            )
          )
        );
        m.bindPopup(pop);
        m.bindTooltip(tip(`${isAssignedOrder ? "🎯 TARGET: " : ""}${victim.name} (${isVulnerable ? "PRIORITAS RENTAN" : "Butuh Evakuasi"}) · ${victim.vulnerability?.join(", ") || "Warga"}`));

        if (isAssignedOrder) {
          m.openPopup();
          navigateToTarget(victim.lat, victim.lng, victim.name, victim);
        }
      });

      const victimPts = allVictims.filter(v => v.lat != null && v.lng != null).map(v => [v.lat, v.lng]);
      if (victimPts.length > 0 && !activeOrder) {
        map.fitBounds(L.latLngBounds(victimPts).pad(0.35));
      }
    }

    map.on("click", e => setPos([e.latlng.lat, e.latlng.lng], "dipilih di peta"));
    if (res?.home_lat != null) setPos([res.home_lat, res.home_lng], "lokasi rumah");
  });
}

// ---------- Peringatan ----------
async function viewAlerts(box) {
  const rows = await api("GET", "/alerts?limit=50");
  const isCoord = ["koordinator", "admin"].includes(me.role);
  box.append(h("h2", {}, "Peringatan"), h("div", { class: "btns no-print", style: "margin-bottom:12px" }, h("button", { class: "sec small", onclick: reload }, "Segarkan")));
  if (!rows.length) box.append(h("div", { class: "notice ok" }, "Belum ada peringatan untuk wilayah Anda."));
  for (const a of rows) {
    const dl = h("div");
    box.append(h("div", { class: "card", style: `border-left:6px solid ${LEVEL_COLOR[a.level] || "#cbd5e1"}` },
      h("div", { class: "btns" }, badge(a.kind.toUpperCase()), a.level ? lvl(a.level) : null,
        a.verification ? verifBadge(a.verification) : null, a.internal ? badge("INTERNAL", "b-warn") : null,
        h("span", { class: "muted small-text" }, `#${a.id}${a.incident_id ? ` · kejadian #${a.incident_id}` : ""} · ${fmt(a.created_at)}`)),
      h("pre", { class: "msg" }, a.message),
      isCoord ? h("button", {
        class: "sec small",
        onclick: act(async () => {
          const d = await api("GET", `/alerts/${a.id}/deliveries`);
          dl.replaceChildren(table([
            { label: "Kanal", key: "channel" }, { label: "Penerima (chat ID)", key: "recipient" },
            { label: "Status", render: x => badge(x.status.toUpperCase(), x.status === "gagal" ? "b-bad" : "b-ok") },
            { label: "Galat", render: x => x.error || "-" }, { label: "Waktu", render: x => fmt(x.created_at) },
          ], d, "Belum ada pengiriman Telegram: tidak ada penerima dengan chat ID."));
        }),
      }, "Status pengiriman Telegram") : null, dl));
  }
}

// ---------- Shelter ----------
async function viewShelters(box, ctx) {
  const rows = await api("GET", "/shelters");
  const isCoord = ["koordinator", "admin"].includes(me.role);
  const canCheckin = isCoord || ["tim_sar", "relawan", "petugas"].includes(me.role);
  box.append(h("h2", {}, "Shelter / Titik Aman"));
  if (!isCoord) box.append(h("div", { class: "notice" }, "Hanya titik aman yang sudah diverifikasi koordinator yang ditampilkan."));
  box.append(h("div", { class: "card" }, h("div", { id: "shmap", class: "map" }), table([
    { label: "Nama", render: s => [h("b", {}, s.name), h("div", { class: "muted small-text" }, s.address)] },
    { label: "Terisi", render: s => `${s.occupancy}/${s.capacity ?? "?"}` },
    { label: "Status", render: s => badge(lab(s.status), { tersedia: "b-ok", terbatas: "b-warn", penuh: "b-bad" }[s.status] || "b-bad") },
    { label: "Verifikasi", render: s => s.is_verified ? badge("TERVERIFIKASI", "b-ok") : badge("BELUM", "b-warn") },
    { label: "", render: s => h("a", { href: gmaps(s.lat, s.lng), target: "_blank", rel: "noopener" }, "Rute") },
    isCoord ? { label: "Aksi", render: s => h("div", { class: "btns" },
      s.is_verified ? null : h("button", { class: "small", onclick: act(async () => { await api("POST", `/shelters/${s.id}/verify`, { note: "Diverifikasi dari UI" }); await reload(); }, "Shelter diverifikasi") }, "Verifikasi"),
      h("select", { onchange: act(async ev => {
        const newSt = ev.target.value;
        await api("POST", `/shelters/${s.id}/status`, { status: newSt });
        if (newSt === "penuh") {
          const doAlert = confirm(`Shelter "${s.name}" ditandai PENUH. Siarkan pengumuman ke Tim SAR, Warga, dan Pos Pantau untuk pengalihan shelter?`);
          if (doAlert) {
            await api("POST", "/alerts/broadcast", {
              message: `UPDATE SHELTER PENUH: ${s.name} telah mencapai batas kapasitas. Warga dan Tim SAR dialihkan ke shelter alternatif terdekat.`,
              level: "waspada"
            });
            toast("Pengumuman pengalihan shelter berhasil disiarkan!");
          }
        }
        await reload();
      }, "Status shelter diubah") },
        opts(["tersedia", "terbatas", "penuh", "tidak_dapat_digunakan"], s.status))) } : null,
  ], rows)));
  ctx.post(() => { const map = newMap($("#shmap")); if (map) addShelters(map, rows); });
  if (canCheckin && rows.length) {
    const sh = h("select", {}, rows.map(s => h("option", { value: s.id }, s.name)));
    const name = h("input", { placeholder: "Nama / rombongan" });
    const n = h("input", { type: "number", min: 1, value: 1 });
    box.append(h("div", { class: "card" }, h("h3", {}, "Check-in warga di shelter (FR-067)"),
      h("div", { class: "row" }, field("Shelter", sh), field("Nama", name), field("Jumlah orang", n),
        h("button", { class: "teal", onclick: act(async () => { await api("POST", `/shelters/${sh.value}/checkin`, { name: name.value.trim(), people_count: Number(n.value) }); await reload(); }, "Check-in tercatat") }, "Check-in"))));
  }
  if (!isCoord) return;
  const regions = await api("GET", "/regions");
  const f = { name: h("input"), address: h("input"), cap: h("input", { type: "number", min: 0 }), lat: h("input", { type: "number", step: "any", value: "-6.8850" }), lng: h("input", { type: "number", step: "any", value: "107.6080" }), contact: h("input") };
  const region = h("select", {}, regionOptions(regions, me.region_id));
  box.append(h("details", { class: "card" }, h("summary", {}, "Tambah shelter"),
    h("div", { class: "row" }, field("Nama", f.name), field("Wilayah", region)), field("Alamat", f.address),
    h("div", { class: "row" }, field("Kapasitas", f.cap), field("Latitude", f.lat), field("Longitude", f.lng), field("Kontak", f.contact)),
    h("button", {
      onclick: act(async () => {
        await api("POST", "/shelters", { name: f.name.value, address: f.address.value, region_id: Number(region.value), capacity: num(f.cap.value), lat: num(f.lat.value), lng: num(f.lng.value), contact: f.contact.value || null });
        await reload();
      }, "Shelter ditambahkan (belum terverifikasi)"),
    }, "Simpan")));
}

// ---------- Modal Detail Pos Pantau (Live Auto-Update) ----------
let stationDetailTimer = null;

async function openStationDetailModal(stationId) {
  if (stationDetailTimer) {
    clearInterval(stationDetailTimer);
    stationDetailTimer = null;
  }

  let modal = document.getElementById("station-detail-modal");
  if (!modal) {
    modal = h("div", {
      id: "station-detail-modal",
      style: "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(11,58,110,.65);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)"
    });
    modal.onclick = (e) => {
      if (e.target === modal) closeModal();
    };
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.style.display === "flex") closeModal();
    });
    document.body.appendChild(modal);
  }

  const closeModal = () => {
    if (stationDetailTimer) {
      clearInterval(stationDetailTimer);
      stationDetailTimer = null;
    }
    modal.style.display = "none";
  };

  modal.replaceChildren(h("div", { class: "card", style: "max-width:680px;width:100%;padding:24px;background:#fff;border-radius:14px" },
    h("p", { class: "muted" }, "Memuat data pos pantau terkini...")
  ));
  modal.style.display = "flex";

  const titleEl = h("h2", { style: "margin:0 0 4px;font-size:22px;color:var(--navy)" }, "Pos Pantau");
  const subTitleEl = h("div", { class: "muted", style: "font-size:14px;font-weight:600" }, "Memuat...");

  const tmaValEl = h("b", { style: "font-size:24px" }, "— cm");
  const tmaBoxEl = h("div", { class: "stat", style: "--c:#0f9d6b" }, tmaValEl, h("span", {}, "Tinggi Muka Air (TMA)"));

  const condValEl = h("b", { style: "font-size:16px" }, "—");
  const condBoxEl = h("div", { class: "stat", style: "--c:#0f9d6b" }, condValEl, h("span", {}, "Status Kondisi"));

  const trendValEl = h("b", { style: "font-size:16px" }, "—");
  const trendBoxEl = h("div", { class: "stat", style: "--c:#0a64b8" }, trendValEl, h("span", {}, "Arah Tren"));

  const thresholdValEl = h("b", { style: "font-size:15px" }, "— / — cm");
  const thresholdBoxEl = h("div", { class: "stat", style: "--c:#64748b" }, thresholdValEl, h("span", {}, "Waspada / Bahaya"));

  const chartBoxEl = h("div", { style: "min-height:180px" });

  const techCoordsEl = h("b", {}, "—");
  const techRegionEl = h("b", {}, "—");
  const techWarnEl = h("b", {}, "—");
  const techDangerEl = h("b", {}, "—");
  const techNoteEl = h("div", { style: "margin-top:8px;font-size:13px", class: "muted" }, "");

  const gmapsBtn = h("button", { class: "sec small", type: "button" }, "Buka Google Maps ↗");
  const controlContainer = h("div", { style: "margin-top:10px;padding-top:10px;border-top:1px solid var(--line)" });

  const content = h("div", {},
    h("div", { style: "display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px;border-bottom:1px solid var(--line);padding-bottom:12px" },
      h("div", {},
        titleEl,
        subTitleEl
      ),
      h("div", { style: "display:flex;align-items:center;gap:8px" },
        h("span", { style: "display:inline-flex;align-items:center;gap:4px;font-size:12px;background:#e0f2fe;color:#0369a1;padding:3px 8px;border-radius:12px;font-weight:700" },
          h("span", { style: "width:8px;height:8px;border-radius:50%;background:#0284c7;display:inline-block" }),
          "Live Monitoring"
        ),
        h("button", { class: "ghost small", style: "font-size:22px;padding:2px 10px;line-height:1;border-radius:8px", onclick: closeModal }, "✕")
      )
    ),

    // Grid Metrik TMA & Ambang
    h("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px" },
      tmaBoxEl, condBoxEl, trendBoxEl, thresholdBoxEl
    ),

    // Grafik SVG Riwayat 12 Jam
    h("div", { style: "margin-bottom:16px" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px" },
        h("h3", { style: "margin:0;font-size:15px;color:var(--navy)" }, "Grafik Ketinggian Air (12 Jam Terakhir)"),
        h("span", { class: "muted small-text" }, "Diperbarui otomatis tiap 3 detik")
      ),
      chartBoxEl
    ),

    // Detail Teknis & Lokasi
    h("div", { class: "card", style: "background:var(--soft);border:none;margin-bottom:14px;padding:14px" },
      h("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13.5px" },
        h("div", {}, h("span", { class: "muted" }, "Koordinat: "), techCoordsEl),
        h("div", {}, h("span", { class: "muted" }, "Wilayah ID: "), techRegionEl),
        h("div", {}, h("span", { class: "muted" }, "Batas Waspada: "), techWarnEl),
        h("div", {}, h("span", { class: "muted" }, "Batas Bahaya/Meluap: "), techDangerEl)
      ),
      techNoteEl,
      h("div", { class: "btns", style: "margin-top:12px" },
        gmapsBtn,
        h("button", { class: "teal small", onclick: () => { closeModal(); location.hash = "#peta"; } }, "Navigasi Shelter Terdekat")
      )
    ),

    controlContainer,

    h("div", { style: "display:flex;justify-content:flex-end;margin-top:16px" },
      h("button", { class: "sec", onclick: closeModal }, "Tutup")
    )
  );

  modal.replaceChildren(h("div", { class: "card", style: "max-width:680px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 12px 36px rgba(0,0,0,.35);padding:22px;background:#fff;border-radius:14px" }, content));

  const refreshModalData = async () => {
    if (modal.style.display === "none") {
      if (stationDetailTimer) { clearInterval(stationDetailTimer); stationDetailTimer = null; }
      return;
    }
    try {
      const [station, trend, liveList] = await Promise.all([
        api("GET", "/stations").then(list => list.find(x => x.id === stationId)),
        api("GET", `/stations/${stationId}/trend?hours=12`),
        api("GET", "/stations/live").then(list => list.find(x => x.id === stationId))
      ]);
      if (!station) return;

      const s = { ...station, ...(liveList || {}) };
      const cond = s.current_condition || "normal";
      const isBahaya = trend.status === "bahaya" || cond === "meluap";
      const isWaspada = trend.status === "waspada" || cond === "waspada";
      const statusColor = isBahaya ? "#dc2626" : isWaspada ? "#d97706" : "#0f9d6b";

      titleEl.textContent = s.name;
      subTitleEl.textContent = `${s.river_name || "Sungai di Bandung"} · ${s.is_upstream ? "Pos Hulu" : "Pos Hilir"}`;

      tmaValEl.textContent = `${s.latest?.level_cm ?? "—"} cm`;
      tmaBoxEl.style.setProperty("--c", statusColor);

      condValEl.textContent = (cond || trend.status).toUpperCase();
      condBoxEl.style.setProperty("--c", statusColor);

      trendValEl.textContent = lab(trend.direction || "stabil");
      thresholdValEl.textContent = `${s.warning_cm} / ${s.danger_cm} cm`;

      techCoordsEl.textContent = `${s.lat.toFixed(4)}, ${s.lng.toFixed(4)}`;
      techRegionEl.textContent = `#${s.region_id}`;
      techWarnEl.textContent = `${s.warning_cm} cm`;
      techDangerEl.textContent = `${s.danger_cm} cm`;

      if (s.latest?.note) {
        techNoteEl.textContent = `Catatan terakhir: ${s.latest.note} (${fmt(s.latest.observed_at)})`;
      } else {
        techNoteEl.textContent = `Diperbarui: ${fmt(s.latest?.observed_at || new Date().toISOString())}`;
      }

      gmapsBtn.onclick = () => window.open(gmaps(s.lat, s.lng), "_blank", "noopener");

      chartBoxEl.replaceChildren(chart(trend.readings || [], s));

      const canControl = me.role === "pos_pantau";
      if (canControl) {
        const changeCondition = async (targetCond) => {
          await api("POST", `/stations/${s.id}/condition`, { condition: targetCond });
          const notifMsg = targetCond === "normal"
            ? `Kondisi ${s.name} kembali NORMAL`
            : `Kondisi ${s.name} diubah ke ${targetCond.toUpperCase()}! Peringatan darurat dikirim ke Telegram & SMS.`;
          toast(notifMsg);
          await refreshModalData();
        };

        const btnNormal = h("button", {
          type: "button",
          class: "btn-cond normal " + (cond === "normal" ? "active" : ""),
          onclick: act(() => changeCondition("normal"))
        }, "🟢 NORMAL", h("small", {}, `< ${s.warning_cm} cm`));

        const btnWaspada = h("button", {
          type: "button",
          class: "btn-cond waspada " + (cond === "waspada" ? "active" : ""),
          onclick: act(() => changeCondition("waspada"))
        }, "🟡 WASPADA", h("small", {}, `${s.warning_cm} - ${s.danger_cm} cm`));

        const btnMeluap = h("button", {
          type: "button",
          class: "btn-cond meluap " + (cond === "meluap" ? "active" : ""),
          onclick: act(() => changeCondition("meluap"))
        }, "🔴 MELUAP", h("small", {}, `> ${s.danger_cm} cm`));

        controlContainer.replaceChildren(
          h("div", { style: "font-weight:800;font-size:13px;color:var(--navy);margin-bottom:6px" }, "Tombol Kontrol Kondisi Sungai (Pos Pantau / Koordinator):"),
          h("div", { class: "condition-btns" }, btnNormal, btnWaspada, btnMeluap)
        );
      } else {
        controlContainer.replaceChildren();
      }
    } catch (err) {
      console.warn("Error updating station modal:", err);
    }
  };

  await refreshModalData();
  stationDetailTimer = setInterval(refreshModalData, 3000);
}

// ---------- Live Monitoring Hidrometeorologi & Kontrol Pos Pantau ----------
async function viewLiveMonitoring(box) {
  const [stations, weather] = await Promise.all([
    api("GET", "/stations/live"),
    api("GET", "/weather/live")
  ]);

  const canControl = me.role === "pos_pantau";
  const alertStation = stations.find(s => s.status === "bahaya" || s.current_condition === "meluap" || s.status === "waspada");

  // Header tanpa teks LIVE (Update tiap 3 detik)
  box.append(
    h("div", { style: "margin-bottom:14px" },
      h("h2", { style: "margin:0" }, "Live Monitoring Sungai & Cuaca Bandung")
    )
  );

  // Early Warning Banner jika ada status waspada / meluap
  if (alertStation) {
    const isMeluap = alertStation.status === "bahaya" || alertStation.current_condition === "meluap";
    box.append(
      h("div", { class: "hero " + (isMeluap ? "l-evakuasi" : "l-waspada"), style: "margin-bottom:16px" },
        h("small", {}, `PERINGATAN DINI & PREDIKSI BANJIR BANDUNG · ${alertStation.river_name || alertStation.name}`),
        h("h1", {}, isMeluap ? "STATUS AIR: MELUAP (SIAGA TINGGI)" : "STATUS AIR: WASPADA LUAPAN"),
        h("p", {}, `Ketinggian air saat ini ${alertStation.latest?.level_cm || "—"} cm. Curah hujan ${weather.rain_mm || 0} mm/jam. Aliran air hulu diprediksi meluap ke kawasan permukiman dalam 30–60 menit. Warga diimbau bersiap dan menuju shelter aman.`),
        h("div", { class: "btns", style: "margin-top:10px" },
          h("button", { class: "teal", onclick: () => { location.hash = "#peta"; } }, "Navigasi Shelter Terdekat →"),
          h("button", { class: "sec", onclick: () => { location.hash = "#alerts"; } }, "Lihat Peringatan Resmi")
        )
      )
    );
  }

  // Live Weather Card (Open-Meteo API) dengan fallback inline styles agar tidak dempet
  box.append(
    h("div", { class: "weather-hero", style: "background:linear-gradient(135deg,var(--navy),#0e7c86);color:#fff;border-radius:14px;padding:20px 22px;margin-bottom:16px;box-shadow:0 4px 18px rgba(11,58,110,.14)" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px" },
        h("h3", { style: "color:#fff;margin:0;font-size:17px;font-weight:800" }, `Cuaca ${weather.location || "Kota Bandung"}`),
        h("span", { class: "badge b-info", style: "background:rgba(255,255,255,.22);color:#fff;font-weight:700" }, weather.source || "Open-Meteo API")
      ),
      h("p", { style: "margin:8px 0 0;font-size:16px;font-weight:700" }, `${weather.condition || "Berawan"} · Curah Hujan: ${weather.rain_mm || 0} mm/jam`),
      h("div", { class: "w-grid", style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-top:14px" },
        h("div", { class: "w-item", style: "background:rgba(255,255,255,.14);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.2)" },
          h("span", { style: "display:block;font-size:12px;opacity:0.9;margin-bottom:2px" }, "Suhu Udara"),
          h("b", { style: "display:block;font-size:20px;font-weight:800" }, `${weather.temperature_c ?? 24} °C`)
        ),
        h("div", { class: "w-item", style: "background:rgba(255,255,255,.14);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.2)" },
          h("span", { style: "display:block;font-size:12px;opacity:0.9;margin-bottom:2px" }, "Curah Hujan"),
          h("b", { style: "display:block;font-size:20px;font-weight:800" }, `${weather.rain_mm ?? 0} mm/jam`)
        ),
        h("div", { class: "w-item", style: "background:rgba(255,255,255,.14);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.2)" },
          h("span", { style: "display:block;font-size:12px;opacity:0.9;margin-bottom:2px" }, "Kelembapan"),
          h("b", { style: "display:block;font-size:20px;font-weight:800" }, `${weather.humidity_pct ?? 80} %`)
        ),
        h("div", { class: "w-item", style: "background:rgba(255,255,255,.14);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.2)" },
          h("span", { style: "display:block;font-size:12px;opacity:0.9;margin-bottom:2px" }, "Kecepatan Angin"),
          h("b", { style: "display:block;font-size:20px;font-weight:800" }, `${weather.wind_speed_kmh ?? 10} km/j`)
        )
      )
    )
  );

  box.append(
    h("div", { style: "margin-bottom:10px" },
      h("h3", { style: "margin:0 0 4px" }, "Kondisi Ketinggian Air Sungai (TMA) Terkini"),
      h("p", { class: "muted small-text", style: "margin:0" }, "Klik pada nama pos pantau untuk melihat grafik ketinggian air 12 jam, riwayat, dan detail teknis.")
    )
  );

  const cards = stations.map(s => {
    const cond = s.current_condition || "normal";
    const lvl = s.latest?.level_cm != null ? s.latest.level_cm : "—";
    const statusClass = s.status === "bahaya" ? "g-meluap" : s.status === "waspada" ? "g-waspada" : "g-normal";
    const cardBorderColor = s.status === "bahaya" ? "#f87171" : s.status === "waspada" ? "#fbd89a" : "#a3e6c5";

    const card = h("div", {
      class: "station-live-card c-" + cond,
      style: `background:#fff;border-radius:14px;border:2px solid ${cardBorderColor};padding:18px 20px;margin-bottom:14px;box-shadow:0 2px 8px rgba(11,58,110,.06)`
    },
      h("div", { style: "display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px" },
        h("div", {
          style: "cursor:pointer;flex:1;min-width:220px",
          onclick: () => openStationDetailModal(s.id),
          title: "Klik untuk melihat grafik & riwayat lengkap"
        },
          h("div", { style: "display:flex;align-items:center;gap:8px;flex-wrap:wrap" },
            h("b", { style: "font-size:18px;color:var(--blue);text-decoration:underline" }, s.name),
            h("span", { style: "font-size:11.5px;background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:6px;font-weight:700" }, "🔍 Lihat Detail & Grafik")
          ),
          h("div", { class: "muted small-text", style: "margin-top:2px" }, `${s.river_name || "Sungai"} ${s.is_upstream ? " · Hulu" : " · Hilir"} · Ambang waspada: ${s.warning_cm} cm | bahaya: ${s.danger_cm} cm`)
        ),
        h("span", { class: "badge " + (s.status === "bahaya" ? "b-evakuasi" : s.status === "waspada" ? "b-waspada" : "b-ok") },
          (s.current_condition || s.status).toUpperCase()
        )
      ),
      h("div", { style: "display:flex;align-items:baseline;gap:12px;margin:10px 0" },
        h("div", { class: "water-gauge " + statusClass, style: "font-size:36px;font-weight:900" }, `${lvl} cm`),
        h("span", { class: "muted", style: "font-weight:700;font-size:14px" }, `Tren: ${lab(s.trend || "stabil")}`)
      ),
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px" },
        h("div", { class: "muted small-text" },
          s.latest?.note ? `Catatan: ${s.latest.note} · ${fmt(s.latest.observed_at)}` : "Menunggu pengamatan baru..."
        ),
        h("button", {
          class: "ghost small",
          style: "padding:3px 10px;font-size:12px;color:var(--teal)",
          type: "button",
          onclick: () => openStationDetailModal(s.id)
        }, "Buka Detail →")
      )
    );

    if (canControl) {
      const btnNormal = h("button", {
        type: "button",
        class: "btn-cond normal " + (cond === "normal" ? "active" : ""),
        onclick: act(async () => {
          await api("POST", `/stations/${s.id}/condition`, { condition: "normal" });
          toast(`Kondisi ${s.name} diubah ke NORMAL`);
          await reload();
        })
      }, "🟢 NORMAL", h("small", {}, `< ${s.warning_cm} cm (Aman)`));

      const btnWaspada = h("button", {
        type: "button",
        class: "btn-cond waspada " + (cond === "waspada" ? "active" : ""),
        onclick: act(async () => {
          await api("POST", `/stations/${s.id}/condition`, { condition: "waspada" });
          toast(`Kondisi ${s.name} diubah ke WASPADA! Peringatan dikirim ke Telegram & SMS.`);
          await reload();
        })
      }, "🟡 WASPADA", h("small", {}, `${s.warning_cm} - ${s.danger_cm} cm`));

      const btnMeluap = h("button", {
        type: "button",
        class: "btn-cond meluap " + (cond === "meluap" ? "active" : ""),
        onclick: act(async () => {
          await api("POST", `/stations/${s.id}/condition`, { condition: "meluap" });
          toast(`Kondisi ${s.name} diubah ke MELUAP! Peringatan bahaya dikirim ke Telegram & SMS.`);
          await reload();
        })
      }, "🔴 MELUAP", h("small", {}, `> ${s.danger_cm} cm (Bahaya)`));

      card.append(
        h("div", { style: "margin-top:14px;padding-top:10px;border-top:1px solid var(--line)" },
          h("div", { style: "font-weight:800;font-size:13px;color:var(--navy);margin-bottom:6px" }, "Tombol Kontrol Kondisi Sungai (Khusus Pos Pantau):"),
          h("div", { class: "condition-btns" }, btnNormal, btnWaspada, btnMeluap),
          h("div", { class: "muted small-text", style: "margin-top:6px" }, "⚡ Mengubah status sungai, menyiarkan peringatan darurat ke Telegram & SMS, dan update live 3 detik.")
        )
      );
    }

    return card;
  });

  box.append(...cards);
}

// ---------- Pos pantau ----------
async function viewStations(box) {
  const stations = await api("GET", "/stations");
  const canInput = ["pos_pantau", "koordinator", "admin"].includes(me.role);
  const canCreate = ["koordinator", "admin"].includes(me.role);
  const panel = h("div");
  const stBadge = s => badge(lab(s).toUpperCase(), { normal: "b-ok", waspada: "b-waspada", bahaya: "b-evakuasi" }[s] || "b-warn");

  async function select(s) {
    const t = await api("GET", `/stations/${s.id}/trend?hours=12`);
    const level = h("input", { type: "number", min: 0, step: "any", placeholder: "cm", style: "font-size:20px;font-weight:700" });
    const cond = h("select", {}, opts(["normal", "naik", "arus_deras", "meluap"]));
    const note = h("input", { placeholder: "catatan (opsional)" });
    const sim = h("input", { type: "checkbox" });
    panel.replaceChildren(h("div", { class: "card" },
      h("h3", {}, `${s.name}${s.is_upstream ? " (hulu)" : ""} — ${s.river_name || ""}`),
      h("div", { class: "btns", style: "margin-bottom:10px" }, stBadge(t.status), badge("Tren: " + t.direction.replaceAll("_", " "), "b-info"), t.stale ? badge("DATA LAMA", "b-warn") : null),
      chart(t.readings, s),
      canInput ? [h("h3", { style: "margin-top:16px" }, "Input pengamatan tinggi air"),
        h("div", { class: "row" }, field("Tinggi air (cm)", level), field("Kondisi sungai", cond), field("Catatan", note)),
        h("label", { class: "chk" }, sim, "Data simulasi (demo)"),
        h("button", {
          onclick: act(async () => {
            if (level.value === "") throw new Error("Isi tinggi air");
            await api("POST", `/stations/${s.id}/observations`, { level_cm: Number(level.value), river_condition: cond.value, note: note.value || null, source_mode: sim.checked ? "simulation" : "real" });
            const fresh = (await api("GET", "/stations")).find(x => x.id === s.id);
            await select(fresh);
          }, "Pengamatan tersimpan"),
        }, "Simpan pengamatan")] : null));
  }
  box.append(h("h2", {}, "Pos Pantau"), h("div", { class: "grid" }, stations.map(s => h("div", { class: "stat", style: `--c:${{ waspada: "#d97706", bahaya: "#dc2626", normal: "#0f9d6b" }[s.status] || "#64748b"};cursor:pointer`, onclick: act(() => select(s)) },
    h("b", {}, s.latest ? `${s.latest.level_cm} cm` : "—"), h("span", {}, `${s.name}${s.is_upstream ? " · hulu" : ""} · ${lab(s.status)}`)))), panel);
  if (stations.length) await select(stations[0]);
  if (!canCreate) return;
  const regions = await api("GET", "/regions");
  const f = { name: h("input"), river: h("input"), w: h("input", { type: "number", value: 150 }), d: h("input", { type: "number", value: 250 }), lat: h("input", { type: "number", step: "any", value: "-6.8800" }), lng: h("input", { type: "number", step: "any", value: "107.6100" }), up: h("input", { type: "checkbox" }) };
  const region = h("select", {}, regionOptions(regions, me.region_id));
  box.append(h("details", { class: "card" }, h("summary", {}, "Tambah pos pantau"),
    h("div", { class: "row" }, field("Nama", f.name), field("Sungai", f.river), field("Wilayah", region)),
    h("div", { class: "row" }, field("Ambang waspada (cm)", f.w), field("Ambang bahaya (cm)", f.d), field("Latitude", f.lat), field("Longitude", f.lng)),
    h("label", { class: "chk" }, f.up, "Pos hulu"),
    h("button", {
      onclick: act(async () => {
        await api("POST", "/stations", { name: f.name.value, river_name: f.river.value || null, region_id: Number(region.value), warning_cm: Number(f.w.value), danger_cm: Number(f.d.value), lat: num(f.lat.value), lng: num(f.lng.value), is_upstream: f.up.checked });
        await reload();
      }, "Pos pantau ditambahkan"),
    }, "Simpan")));
}

// ---------- Dashboard ----------
async function viewDashboard(box, ctx) {
  const [d, shelters, tasks, hazards, routes] = await Promise.all([api("GET", "/dashboard"), api("GET", "/shelters"), api("GET", "/tasks?active=true"),
    api("GET", "/road-conditions"), api("GET", "/evacuation-routes")]);
  const by = d.residents.by_status;
  const stat = (n, t, c) => h("div", { class: "stat", style: `--c:${c}` }, h("b", {}, n), h("span", {}, t));
  const top = d.incidents.reduce((m, i) => LEVEL_RANK[i.level] > (LEVEL_RANK[m?.level] || 0) ? i : m, null);
  box.append(h("h2", {}, "Dashboard Koordinator"),
    top ? h("div", { class: "hero l-" + top.level }, h("small", {}, `${top.is_simulation ? "SIMULASI · " : ""}Kejadian aktif tertinggi · ${lab(top.verification)}`),
      h("h1", {}, `${top.level.toUpperCase()} ${top.hazard.toUpperCase()} — #${top.id}`),
      h("p", {}, `${top.unique_reporters} pelapor unik · laporan terakhir ${fmt(top.last_report_at)}${top.pending_level ? ` · usulan ${top.pending_level.toUpperCase()} otomatis ${fmt(top.pending_deadline)} bila tidak direspons` : ""}`))
      : h("div", { class: "hero" }, h("small", {}, "Kondisi wilayah"), h("h1", {}, "Tidak ada kejadian aktif"), h("p", {}, `Diperbarui ${fmt(d.generated_at)}`)),
    h("div", { class: "grid" },
      stat(d.incidents.length, "Kejadian aktif", "#ea580c"), stat(d.reports_24h.total, "Laporan 24 jam", "#0a64b8"),
      stat(d.help_queue, "Butuh bantuan", "#dc2626"), stat(by.belum_terkonfirmasi, "Belum terkonfirmasi", "#d97706"),
      stat(by.aman_mandiri + by.aman_terverifikasi, "Aman (mandiri + terverifikasi)", "#0f9d6b"), stat(by.tiba_di_titik_aman, "Tiba di titik aman", "#0e7c86"),
      stat(tasks.length, "Tugas relawan aktif", "#0b3a6e")),
    h("div", { class: "cols-2" },
      h("div", { class: "card" }, h("h3", {}, "Peta situasi"),
        legend([["#dc2626", "Kejadian"], ["#64748b", "Laporan"], ["#0f9d6b", "Shelter"], ["#0a64b8", "Pos pantau"], ["#b91c1c", "Bahaya jalan"], ["#7c3aed", "Tugas"]]),
        h("div", { id: "ovmap", class: "map tall" })),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "Kejadian aktif"), table([
          { label: "#", key: "id" }, { label: "Jenis", render: i => [i.hazard, " ", simBadge(i.is_simulation)] },
          { label: "Level", render: i => lvl(i.level) }, { label: "Pelapor", key: "unique_reporters" },
          { label: "", render: i => h("a", { href: "#incidents", onclick: () => store.set("rw_open", i.id) }, "Buka") }], d.incidents, "Tidak ada kejadian aktif.")),
        h("div", { class: "card" }, h("h3", {}, "Pos pantau"), table([
          { label: "Pos", key: "name" }, { label: "Tinggi", render: s => s.latest ? `${s.latest.level_cm} cm ${s.latest.source_mode === "simulation" ? "(SIM)" : ""}` : "-" },
          { label: "Status", render: s => lab(s.status) }], d.stations)),
        h("div", { class: "card" }, h("h3", {}, "Konteks cuaca"), table([
          { label: "Wilayah", render: w => "#" + w.region_id }, { label: "Aktif", render: w => w.is_active ? "Ya" : "Tidak" },
          { label: "Keterangan", render: w => [w.description, " ", simBadge(w.source_mode === "simulation")] }], d.weather, "Belum ada konteks cuaca.")))),
    h("div", { class: "card" }, h("h3", {}, "Peringatan terbaru"), table([
      { label: "Waktu", render: a => fmt(a.created_at) }, { label: "Jenis", key: "kind" },
      { label: "Level", render: a => a.level ? lvl(a.level) : "-" }, { label: "Internal", render: a => a.internal ? "Ya" : "Tidak" },
      { label: "Kejadian", render: a => a.incident_id ? "#" + a.incident_id : "-" }], d.recent_alerts)));
  ctx.post(async () => {
    const map = newMap($("#ovmap"));
    if (!map) return;
    addRoutes(map, routes); addHazards(map, hazards); addShelters(map, shelters);
    const reps = await api("GET", "/reports?limit=200").catch(() => []);
    reps.forEach(r => L.marker([r.lat, r.lng], { icon: dotIcon(r.status === "ditolak" ? "#cbd5e1" : "#64748b") }).addTo(map).bindTooltip(tip(`Laporan #${r.id} ${r.hazard} (${lab(r.status)})`)));
    d.stations.forEach(s => L.marker([s.lat, s.lng], { icon: pinIcon("#0a64b8", "P") }).addTo(map).bindTooltip(tip(`Pos: ${s.name} (${lab(s.status)})`)));
    tasks.filter(t => t.lat != null).forEach(t => L.marker([t.lat, t.lng], { icon: dotIcon("#7c3aed") }).addTo(map).bindTooltip(tip(`Tugas #${t.id} ${t.task_type} · ${lab(t.status)}`)));
    d.incidents.forEach(i => {
      L.circle([i.lat, i.lng], { radius: i.hazard === "banjir" ? 250 : 150, color: LEVEL_COLOR[i.level], weight: 1, fillOpacity: .12 }).addTo(map);
      L.marker([i.lat, i.lng], { icon: pinIcon(LEVEL_COLOR[i.level], "!", LEVEL_RANK[i.level] >= 3) }).addTo(map).bindTooltip(tip(`Kejadian #${i.id} ${i.hazard} — ${i.level.toUpperCase()}`));
    });
  });
}

// ---------- Prioritas evakuasi ----------
async function viewPriorities(box, ctx) {
  const sel = store.get("rw_prio_incident");
  const [d, users, shelters, incidents] = await Promise.all([
    api("GET", "/evacuation/priorities" + (sel ? `?incident_id=${sel}` : "")), api("GET", "/tasks/teams"), api("GET", "/shelters"), api("GET", "/incidents")]);
  const vols = users.filter(u => ["tim_sar", "relawan", "petugas"].includes(u.role) && u.is_active);
  const usable = shelters.filter(s => s.is_verified && ["tersedia", "terbatas"].includes(s.status));
  const incSel = h("select", { onchange: ev => { store.set("rw_prio_incident", ev.target.value || null); reload(); } },
    h("option", { value: "" }, "Kejadian aktif terbaru"), incidents.map(i => h("option", { value: i.id, selected: d.incident?.id === i.id && !!sel }, `#${i.id} ${i.hazard} — ${i.level.toUpperCase()}`)));
  let map = null;
  const counts = { kritis: 0, tinggi: 0, sedang: 0, rendah: 0 };
  d.items.forEach(x => counts[x.priority]++);

  const taskForm = (x, slot) => {
    const type = h("select", {}, opts(["evakuasi", "medis", "logistik", "damkar", "sar", "lainnya"], x.need_type === "medis" ? "medis" : x.need_type === "logistik" ? "logistik" : "evakuasi"));
    const prio = h("select", {}, opts(["kritis", "tinggi", "sedang", "rendah"], x.priority));
    const who = h("select", {}, h("option", { value: "" }, "— belum ditugaskan —"), vols.map(u => h("option", { value: u.id }, u.name)));
    const shel = h("select", {}, h("option", { value: "" }, "— tanpa shelter —"), usable.map(s => h("option", { value: s.id, selected: x.nearest_shelter?.id === s.id }, s.name)));
    const desc = h("textarea", { value: `Jemput ${x.name}${x.vulnerability.length ? " (" + x.vulnerability.join(", ") + ")" : ""}${x.nearest_shelter ? " ke " + x.nearest_shelter.name : ""}.` });
    slot.replaceChildren(h("div", { class: "card flat", style: "margin:8px 0 0;background:var(--soft)" },
      h("div", { class: "row" }, field("Jenis", type), field("Prioritas", prio), field("Tim SAR", who), field("Shelter tujuan", shel)),
      field("Instruksi untuk Tim SAR", desc),
      h("div", { class: "btns" }, h("button", {
        class: "teal", onclick: act(async () => {
          await api("POST", "/tasks", { task_type: type.value, priority: prio.value, description: desc.value, resident_id: x.resident_id, incident_id: d.incident?.id || null, assignee_id: num(who.value), shelter_id: num(shel.value) });
          await reload();
        }, "Tugas penyelamatan dikirim ke Tim SAR"),
      }, "Ajukan Bantuan ke Tim SAR"), h("button", { class: "ghost", onclick: () => slot.replaceChildren() }, "Batal"))));
  };

  box.append(h("h2", {}, "Prioritas Evakuasi"),
    h("div", { class: "notice warn" }, d.note + " Lokasi = lokasi terkini yang dibagikan warga (≤ 6 jam) atau lokasi rumah. Halaman ini tercatat di audit log."),
    h("div", { class: "row no-print", style: "max-width:520px" }, field("Hitung untuk kejadian", incSel), h("button", { class: "sec", onclick: () => window.print() }, "Cetak daftar")),
    d.incident ? h("p", {}, "Kejadian: ", h("b", {}, `#${d.incident.id} ${d.incident.hazard}`), " ", lvl(d.incident.level), " ", verifBadge(d.incident.verification)) : h("p", { class: "muted" }, "Tidak ada kejadian aktif: prioritas dihitung tanpa jarak kejadian."),
    h("div", { class: "grid" }, Object.entries(counts).map(([k, n]) => h("div", { class: "stat", style: `--c:${PRIO_COLOR[k]}` }, h("b", {}, n), h("span", {}, "Prioritas " + k)))),
    h("div", { class: "cols-2" },
      h("div", { class: "card" }, legend(Object.entries(PRIO_COLOR).map(([k, c]) => [c, k])), h("div", { id: "priomap", class: "map tall" })),
      h("div", { class: "card", style: "max-height:76vh;overflow:auto" }, h("h3", {}, `${d.items.length} warga perlu dicek`),
        d.items.length ? d.items.map(x => {
          const slot = h("div");
          return h("div", { class: "prio-item" },
            h("div", { class: "prio-score", style: `background:${PRIO_COLOR[x.priority]}` }, x.score),
            h("div", {},
              h("div", { class: "btns" }, h("b", {}, x.name), prioBadge(x.priority), badge(lab(x.status), x.status === "butuh_bantuan" ? "b-bad" : "b-info"),
                x.has_smartphone ? null : badge("tanpa HP", "b-warn"), x.task ? badge(`tugas #${x.task.id}: ${lab(x.task.status)}`, "b-sim") : null),
              h("div", { class: "factor" }, x.factors.map(f => `+${f.poin} ${f.keterangan}`).join(" · ")),
              h("div", { class: "factor" }, x.lat != null ? `Lokasi ${x.location_source} · ` : "Lokasi belum ada · ",
                x.nearest_shelter ? `shelter terdekat ${x.nearest_shelter.name} (${fmtDist(x.nearest_shelter.distance_m)})` : "tidak ada shelter tersedia"),
              slot),
            h("div", { class: "btns no-print", style: "flex-direction:column" },
              x.lat != null ? h("button", { class: "sec small", onclick: () => map?.setView([x.lat, x.lng], 18) }, "Peta") : null,
              x.task ? null : h("button", { class: "small teal", onclick: () => taskForm(x, slot) }, "Minta Bantuan Tim SAR")));
        }) : h("div", { class: "notice ok" }, "Semua warga di wilayah ini tercatat aman / sudah di titik aman."))));
  ctx.post(() => {
    map = newMap($("#priomap"));
    if (!map) return;
    addShelters(map, shelters);
    if (d.incident) {
      L.circle([d.incident.lat, d.incident.lng], { radius: 1000, color: "#ea580c", weight: 1, dashArray: "4 6", fillOpacity: .03 }).addTo(map);
      L.circle([d.incident.lat, d.incident.lng], { radius: 300, color: "#dc2626", weight: 1, fillOpacity: .08 }).addTo(map);
      L.marker([d.incident.lat, d.incident.lng], { icon: pinIcon(LEVEL_COLOR[d.incident.level], "!", true) }).addTo(map).bindTooltip(tip(`Kejadian #${d.incident.id}`));
    }
    const pts = d.items.filter(x => x.lat != null);
    pts.forEach(x => L.marker([x.lat, x.lng], { icon: dotIcon(PRIO_COLOR[x.priority]) }).addTo(map)
      .bindTooltip(tip(`${x.name} — ${x.priority.toUpperCase()} (${x.score}) · ${lab(x.status)} · lokasi ${x.location_source}`)));
    if (pts.length) map.fitBounds(L.latLngBounds(pts.map(x => [x.lat, x.lng])).pad(0.3));
  });
}

// ---------- Tugas relawan ----------
const FLOW = { baru: [], menunggu_penerimaan: ["diterima", "gagal"], diterima: ["menuju_lokasi", "gagal"], menuju_lokasi: ["dalam_penanganan", "gagal"], dalam_penanganan: ["selesai", "gagal"] };
const NEXT_LABEL = { diterima: "Terima tugas", menuju_lokasi: "Berangkat ke lokasi", dalam_penanganan: "Mulai penanganan", selesai: "Selesai", gagal: "Tidak dapat dilaksanakan", dibatalkan: "Batalkan tugas" };
const STEP_ORDER = ["menunggu_penerimaan", "diterima", "menuju_lokasi", "dalam_penanganan", "selesai"];

function taskCard(t, { shelters = [], vols = [], isCoord = false, myPos = null } = {}) {
  const slot = h("div");
  const idx = STEP_ORDER.indexOf(t.status);
  const doStatus = (status, extra = {}) => act(async () => { await api("POST", `/tasks/${t.id}/status`, { status, ...extra }); await reload(); }, `Status: ${lab(status)}`);
  const finishForm = () => {
    const shel = h("select", {}, h("option", { value: "" }, "— tidak ke shelter —"), shelters.map(s => h("option", { value: s.id, selected: s.id === t.shelter_id }, s.name)));
    const people = h("input", { type: "number", min: 0, value: t.people_count ?? 1 });
    const note = h("textarea", { placeholder: "Catatan hasil penanganan & kondisi korban (wajib)" });
    slot.replaceChildren(h("div", { class: "card flat", style: "margin:8px 0 0;background:var(--soft)" },
      h("h4", { style: "margin:0 0 8px;color:var(--teal);font-size:15px" }, "Laporan Pasca-Penyelamatan Warga (Tim SAR)"),
      h("div", { class: "row" }, field("Evakuasi ke Shelter", shel), field("Jumlah Jiwa Diselamatkan", people)),
      field("Catatan Hasil / Kondisi Korban", note),
      h("button", { class: "green", onclick: act(async () => {
        if (!note.value.trim() || note.value.trim().length < 3) throw new Error("Catatan hasil penanganan wajib diisi (min. 3 karakter)");
        await api("POST", `/tasks/${t.id}/status`, { status: "selesai", note: note.value.trim(), people_count: Number(people.value), shelter_id: num(shel.value) });
        await reload();
      }, "Laporan penyelamatan berhasil dikirim") }, "Kirim Laporan & Selesaikan Tugas")));
  };
  const askReason = status => act(async () => {
    const reason = prompt(status === "gagal" ? "Alasan tugas tidak dapat dilaksanakan (wajib):" : "Alasan membatalkan (wajib):");
    if (!reason) throw new Error("batal");
    await api("POST", `/tasks/${t.id}/status`, { status, note: reason }); await reload();
  }, "Status diperbarui");
  const next = (FLOW[t.status] || []).map(s => s === "selesai" ? h("button", { class: "green", onclick: finishForm }, NEXT_LABEL[s])
    : s === "gagal" ? h("button", { class: "sec", onclick: askReason("gagal") }, NEXT_LABEL[s])
      : h("button", { class: "teal", onclick: doStatus(s) }, NEXT_LABEL[s]));
  const final = ["selesai", "gagal", "dibatalkan"].includes(t.status);
  let reassign = null;
  if (isCoord && ["baru", "menunggu_penerimaan", "diterima"].includes(t.status)) {
    const who = h("select", {}, h("option", { value: "" }, "— pilih relawan —"), vols.map(u => h("option", { value: u.id, selected: u.id === t.assignee_id }, u.name)));
    reassign = h("div", { class: "row", style: "margin-top:8px" }, field(t.assignee_id ? "Tugaskan ulang ke" : "Tugaskan ke", who),
      h("button", { class: "sec", onclick: act(async () => { if (!who.value) throw new Error("Pilih relawan"); await api("POST", `/tasks/${t.id}/assign`, { assignee_id: Number(who.value) }); await reload(); }, "Relawan ditugaskan") }, "Simpan"));
  }
  return h("div", { class: `card task p-${t.priority}-b` },
    h("div", { class: "btns" }, prioBadge(t.priority), badge(t.task_type.toUpperCase(), "b-info"), badge(lab(t.status), final ? (t.status === "selesai" ? "b-ok" : "b-bad") : "b-warn"),
      h("span", { class: "muted small-text" }, `#${t.id} · ${fmt(t.created_at)}${t.assignee_name ? " · " + t.assignee_name : ""}`)),
    h("div", { style: "font-size:17px;font-weight:800;margin-top:8px;color:var(--navy)" }, t.resident_name || "Tugas umum"),
    t.resident_vulnerability.length ? h("div", { class: "btns", style: "margin:4px 0" }, t.resident_vulnerability.map(v => badge(v.replaceAll("_", " "), "b-bad"))) : null,
    h("p", { style: "margin:6px 0" }, t.description),
    t.lat != null ? h("div", { class: "muted small-text" }, `Lokasi ${t.lat.toFixed(5)}, ${t.lng.toFixed(5)}${myPos ? " · ±" + fmtDist(dist(myPos, [t.lat, t.lng])) + " dari Anda" : ""} · `,
      h("a", { href: gmaps(t.lat, t.lng), target: "_blank", rel: "noopener" }, "Rute ke lokasi (Google Maps)")) : null,
    t.lat != null && !final ? h("div", { style: "margin:8px 0" },
      h("button", {
        class: "teal small",
        style: "display:inline-flex;align-items:center;gap:6px;font-weight:700",
        onclick: () => {
          store.set("rw_active_task_nav", {
            id: t.id,
            resident_id: t.resident_id,
            name: t.resident_name || "Korban Evakuasi",
            lat: t.lat,
            lng: t.lng,
            priority: t.priority,
            vulnerability: t.resident_vulnerability || [],
            shelter_id: t.shelter_id
          });
          location.hash = "#peta";
        }
      }, "🎯 Buka Peta & Arahkan Navigasi ke Korban")) : null,
    t.result ? h("div", { class: "notice " + (t.status === "selesai" ? "ok" : "bad"), style: "margin-top:8px" }, "Hasil: " + t.result) : null,
    final ? null : h("div", { class: "steps" }, STEP_ORDER.map((s, i) => h("span", { class: i < idx ? "done" : i === idx ? "now" : "" }, lab(s)))),
    final ? null : h("div", { class: "btns" }, next, isCoord ? h("button", { class: "danger", onclick: askReason("dibatalkan") }, NEXT_LABEL.dibatalkan) : null),
    reassign, slot);
}

async function viewMyTasks(box) {
  const [tasks, shelters] = await Promise.all([api("GET", "/tasks"), api("GET", "/shelters")]);
  let myPos = null;
  try { myPos = (await getPosition(3000)).slice(0, 2); } catch { /* tanpa jarak */ }
  const active = tasks.filter(t => !["selesai", "gagal", "dibatalkan"].includes(t.status));
  const done = tasks.filter(t => !active.includes(t));
  const usable = shelters.filter(s => s.is_verified);
  box.append(h("h2", {}, "Tugas Saya"),
    h("div", { class: "notice" }, "Utamakan keselamatan Anda. Jangan memasuki arus deras atau bangunan terbakar; ikuti arahan Damkar/SAR."),
    h("div", {}, active.length ? active.map(t => taskCard(t, { shelters: usable, myPos })) : h("div", { class: "notice ok" }, "Tidak ada tugas aktif. Anda akan menerima notifikasi saat ditugaskan.")));
  const kind = h("select", {}, opts(["jalan_tertutup", "genangan", "api", "pohon_tumbang", "kabel_listrik", "lainnya"]));
  const note = h("input", { placeholder: "keterangan singkat" });
  box.append(h("div", { class: "card" }, h("h3", {}, "Laporkan hambatan jalan di posisi saya"),
    h("p", { class: "muted small-text" }, "Titik ini dipakai untuk memperingatkan rute evakuasi warga."),
    h("div", { class: "row" }, field("Jenis", kind), field("Keterangan", note),
      h("button", { class: "danger", onclick: act(async () => { const p = await getPosition(); await api("POST", "/road-conditions", { region_id: me.region_id, kind: kind.value, lat: p[0], lng: p[1], note: note.value || null }); note.value = ""; }, "Hambatan jalan dilaporkan") }, "Laporkan"))));
  if (done.length) box.append(h("details", { class: "card" }, h("summary", {}, `Riwayat (${done.length})`), done.map(t => taskCard(t))));
}

async function viewTasks(box, ctx) {
  const [tasks, users, shelters, regions] = await Promise.all([api("GET", "/tasks"), api("GET", "/tasks/teams"), api("GET", "/shelters"), api("GET", "/regions")]);
  const vols = users.filter(u => ["tim_sar", "relawan", "petugas"].includes(u.role) && u.is_active);
  const usable = shelters.filter(s => s.is_verified);
  const showAll = store.get("rw_tasks_all", false);
  const list = tasks.filter(t => showAll || !["selesai", "gagal", "dibatalkan"].includes(t.status));
  const f = { type: h("select", {}, opts(["evakuasi", "medis", "logistik", "damkar", "sar", "lainnya"])), prio: h("select", {}, opts(["kritis", "tinggi", "sedang", "rendah"], "sedang")),
    region: h("select", {}, regionOptions(regions, me.region_id)), desc: h("textarea", { placeholder: "Instruksi tugas" }),
    who: h("select", {}, h("option", { value: "" }, "— belum ditugaskan —"), vols.map(u => h("option", { value: u.id }, u.name))),
    shel: h("select", {}, h("option", { value: "" }, "— tanpa shelter —"), usable.map(s => h("option", { value: s.id }, s.name))),
    lat: h("input", { type: "number", step: "any" }), lng: h("input", { type: "number", step: "any" }) };
  box.append(h("h2", {}, "Tugas Tim SAR & Penyelamatan"),
    h("div", { class: "btns no-print", style: "margin-bottom:12px" },
      h("button", { class: "sec small", onclick: () => { store.set("rw_tasks_all", !showAll); reload(); } }, showAll ? "Hanya tugas aktif" : "Tampilkan semua (termasuk selesai)"),
      h("button", { class: "sec small", onclick: () => window.print() }, "Cetak daftar tugas"),
      h("a", { href: "#prioritas" }, h("button", { class: "small", type: "button" }, "Buat dari prioritas evakuasi"))),
    h("div", { class: "cols-2" },
      h("div", {}, list.length ? list.map(t => taskCard(t, { shelters: usable, vols, isCoord: true })) : h("div", { class: "notice ok" }, "Tidak ada tugas aktif.")),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "Peta tugas"), h("div", { id: "taskmap", class: "map" })),
        h("details", { class: "card no-print" }, h("summary", {}, "Buat tugas umum (tanpa warga tertentu)"),
          h("div", { class: "row" }, field("Jenis", f.type), field("Prioritas", f.prio)), field("Wilayah", f.region), field("Instruksi", f.desc),
          h("div", { class: "row" }, field("Tim SAR", f.who), field("Shelter", f.shel)),
          h("p", { class: "muted small-text" }, "Ketuk peta tugas untuk mengisi lokasi."), h("div", { class: "row" }, field("Lat", f.lat), field("Lng", f.lng)),
          h("button", { class: "teal", onclick: act(async () => { await api("POST", "/tasks", { task_type: f.type.value, priority: f.prio.value, region_id: Number(f.region.value), description: f.desc.value, assignee_id: num(f.who.value), shelter_id: num(f.shel.value), lat: num(f.lat.value), lng: num(f.lng.value) }); await reload(); }, "Tugas dibuat") }, "Buat tugas")))));
  ctx.post(() => {
    const map = newMap($("#taskmap"));
    if (!map) return;
    addShelters(map, shelters);
    list.filter(t => t.lat != null).forEach(t => L.marker([t.lat, t.lng], { icon: pinIcon(PRIO_COLOR[t.priority], "T") }).addTo(map).bindTooltip(tip(`#${t.id} ${t.resident_name || t.task_type} · ${lab(t.status)}`)));
    map.on("click", e => { f.lat.value = e.latlng.lat.toFixed(6); f.lng.value = e.latlng.lng.toFixed(6); });
  });
}

// ---------- Peta & rute (koordinator) ----------
async function viewRouteAdmin(box, ctx) {
  const [routes, hazards, shelters, regions] = await Promise.all([api("GET", "/evacuation-routes"), api("GET", "/road-conditions"), api("GET", "/shelters"), api("GET", "/regions")]);
  let mode = "lihat", draft = [], draftLine = null, map = null;
  const region = h("select", {}, regionOptions(regions, me.region_id));
  const kind = h("select", {}, opts(["jalan_tertutup", "genangan", "api", "pohon_tumbang", "kabel_listrik", "lainnya"]));
  const hnote = h("input", { placeholder: "keterangan" });
  const rname = h("input", { placeholder: "mis. Jalur Gang Melati" });
  const rshel = h("select", {}, shelters.map(s => h("option", { value: s.id }, s.name)));
  const info = h("div", { class: "notice" });
  const hazardBox = h("div", {}, h("div", { class: "row" }, field("Jenis bahaya", kind), field("Keterangan", hnote)));
  const routeBox = h("div", {}, h("div", { class: "row" }, field("Nama rute", rname), field("Shelter tujuan", rshel)),
    h("div", { class: "btns" },
      h("button", { class: "teal", onclick: act(async () => { if (draft.length < 2) throw new Error("Minimal 2 titik"); await api("POST", "/evacuation-routes", { name: rname.value.trim(), region_id: Number(region.value), shelter_id: Number(rshel.value), points: draft }); await reload(); }, "Rute disimpan (belum diverifikasi)") }, "Simpan rute"),
      h("button", { class: "sec", onclick: () => { draft.pop(); draftLine?.setLatLngs(draft); } }, "Hapus titik terakhir")));
  const setMode = m => {
    mode = m; draft = []; if (draftLine) { draftLine.remove(); draftLine = null; }
    info.textContent = { lihat: "Mode lihat.", bahaya: "Ketuk peta untuk menandai titik bahaya jalan.", rute: "Ketuk peta berurutan dari permukiman ke shelter (min. 2 titik), lalu Simpan rute." }[m];
    hazardBox.hidden = m !== "bahaya"; routeBox.hidden = m !== "rute";
  };
  box.append(h("h2", {}, "Peta & Rute Evakuasi"),
    h("div", { class: "notice warn" }, "Rute terpendek belum tentu aman (PRD §14.2). Hanya rute berstatus TERVERIFIKASI yang ditampilkan sebagai rute resmi aman ke warga."),
    h("div", { class: "cols-2" },
      h("div", { class: "card" }, legend(Object.entries(ROUTE_STYLE).map(([k, s]) => [s.color, lab(k)])), h("div", { id: "rmap", class: "map tall" })),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "Alat"),
          h("div", { class: "btns", style: "margin-bottom:10px" }, ["lihat", "bahaya", "rute"].map(m => h("button", { class: "sec small", onclick: () => setMode(m) }, { lihat: "Lihat", bahaya: "Tandai bahaya", rute: "Gambar rute" }[m]))),
          field("Wilayah", region), info, hazardBox, routeBox),
        h("div", { class: "card" }, h("h3", {}, "Rute resmi"), table([
          { label: "Rute", render: r => [h("b", {}, r.name), h("div", { class: "muted small-text" }, `${r.points.length} titik · ${fmt(r.updated_at)}`)] },
          { label: "Status", render: r => h("select", { onchange: act(async ev => { await api("POST", `/evacuation-routes/${r.id}/status`, { status: ev.target.value, note: "Diubah dari UI" }); await reload(); }, "Status rute diubah") }, opts(Object.keys(ROUTE_STYLE), r.status)) }], routes)),
        h("div", { class: "card" }, h("h3", {}, "Titik bahaya aktif"), table([
          { label: "Jenis", render: x => [h("b", {}, lab(x.kind)), " ", simBadge(x.source_mode === "simulation"), h("div", { class: "muted small-text" }, x.note || "")] },
          { label: "Sejak", render: x => fmt(x.created_at) },
          { label: "", render: x => h("button", { class: "small sec", onclick: act(async () => { await api("POST", `/road-conditions/${x.id}/resolve`); await reload(); }, "Ditandai selesai") }, "Selesai") }], hazards, "Tidak ada titik bahaya aktif.")))));
  setMode("lihat");
  ctx.post(() => {
    map = newMap($("#rmap"));
    if (!map) return;
    addRoutes(map, routes); addHazards(map, hazards); addShelters(map, shelters);
    map.on("click", act(async e => {
      if (mode === "bahaya") {
        await api("POST", "/road-conditions", { region_id: Number(region.value), kind: kind.value, lat: e.latlng.lat, lng: e.latlng.lng, note: hnote.value || null });
        toast("Titik bahaya ditambahkan"); await reload();
      } else if (mode === "rute") {
        draft.push([+e.latlng.lat.toFixed(6), +e.latlng.lng.toFixed(6)]);
        draftLine ? draftLine.setLatLngs(draft) : (draftLine = L.polyline(draft, { color: "#7c3aed", weight: 5 }).addTo(map));
      }
    }));
  });
}

// ---------- Kejadian ----------
async function viewIncidents(box) {
  const status = h("select", {}, opts(["aktif", "selesai", "dibatalkan"], store.get("rw_inc_status", "aktif")));
  status.onchange = () => { store.set("rw_inc_status", status.value); reload(); };
  const rows = await api("GET", "/incidents?status=" + status.value);
  const detail = h("div");
  const open = async id => {
    const [i, hist, alerts] = await Promise.all([api("GET", `/incidents/${id}`), api("GET", `/incidents/${id}/history`), api("GET", `/alerts?incident_id=${id}&limit=20`)]);
    const reason = h("input", { placeholder: "Alasan (wajib untuk ubah level, batal, tutup, tolak usulan)" });
    const level = h("select", {}, opts(["pantau", "waspada", "siaga", "evakuasi"], i.level));
    const live = i.status === "aktif";
    const go = (fn, ok) => act(async () => { await fn(); toast(ok); await open(id); });
    const changeLevel = go(async () => {
      if (level.value === "evakuasi" && !confirm("Evakuasi adalah keputusan pihak berwenang sesuai SOP. Lanjutkan hanya bila Anda berwenang menetapkannya.")) throw new Error("batal");
      await api("POST", `/incidents/${id}/level`, { level: level.value, reason: reason.value });
    }, "Level ditetapkan");
    detail.replaceChildren(h("div", { class: "card", style: `border-left:6px solid ${LEVEL_COLOR[i.level]}` },
      h("h3", {}, `Kejadian #${i.id} — ${i.hazard} `, lvl(i.level), " ", verifBadge(i.verification), " ", simBadge(i.is_simulation)),
      h("p", { class: "muted" }, `Status ${i.status} · ${i.unique_reporters} pelapor unik · skor ${i.score} · mulai ${fmt(i.started_at)}`),
      i.pending_level ? h("div", { class: "notice warn" }, `Usulan ${i.pending_level.toUpperCase()} menunggu sejak ${fmt(i.pending_since)}. Tanpa respons, naik otomatis dengan label BELUM DIVERIFIKASI.`) : null,
      live ? [field("Alasan / catatan", reason),
        h("div", { class: "row" }, field("Level baru", level), h("div", { class: "btns" }, h("button", { onclick: changeLevel }, "Tetapkan level"),
          h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/verify`, { note: reason.value || null }), "Kejadian diverifikasi") }, "Tandai terverifikasi"),
          i.pending_level ? h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/proposal/dismiss`, { reason: reason.value }), "Usulan ditolak") }, "Tolak usulan") : null,
          h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/close`, { reason: reason.value }), "Kejadian ditutup") }, "Tutup / selesai"),
          h("button", { class: "danger", onclick: go(() => api("POST", `/incidents/${id}/cancel`, { reason: reason.value }), "Kejadian dibatalkan") }, "Batalkan")))] : null),
      h("div", { class: "card" }, h("h3", {}, "Laporan dalam kejadian"), reportsTable(i.reports, () => open(id))),
      h("div", { class: "card" }, h("h3", {}, "Riwayat perubahan"), table([
        { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Aksi", key: "action" },
        { label: "Pelaku", render: x => x.actor_id ? "user #" + x.actor_id : "sistem" },
        { label: "Perubahan", render: x => (x.old_value ? JSON.stringify(x.old_value) + " → " : "") + JSON.stringify(x.new_value || {}) },
        { label: "Alasan", render: x => x.reason || "-" }], hist)),
      h("div", { class: "card" }, h("h3", {}, "Alert kejadian ini"), table([
        { label: "#", key: "id" }, { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Jenis", key: "kind" },
        { label: "Internal", render: x => x.internal ? "Ya" : "Tidak" }, { label: "Pesan", render: x => h("pre", { class: "msg" }, x.message) }], alerts)));
    detail.scrollIntoView({ behavior: "smooth" });
  };
  box.append(h("h2", {}, "Kejadian"), h("div", { class: "row", style: "max-width:300px" }, field("Status", status)),
    h("div", { class: "card" }, table([
      { label: "#", key: "id" }, { label: "Jenis", render: i => [i.hazard, " ", simBadge(i.is_simulation)] },
      { label: "Level", render: i => lvl(i.level) }, { label: "Verifikasi", render: i => verifBadge(i.verification) },
      { label: "Pelapor unik", key: "unique_reporters" }, { label: "Terakhir", render: i => fmt(i.last_report_at) },
      { label: "", render: i => h("button", { class: "small", onclick: act(() => open(i.id)) }, "Buka") },
    ], rows, "Tidak ada kejadian.")), detail);
  const want = store.get("rw_open");
  if (want) { store.del("rw_open"); await open(Number(want)); }
}

// ---------- Modal Terima & Tolak Laporan (Pos Pantau / Koordinator) ----------
function openAcceptReportModal(r, after) {
  let modal = document.getElementById("accept-report-modal");
  if (!modal) {
    modal = h("div", {
      id: "accept-report-modal",
      style: "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(11,58,110,.65);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)"
    });
    modal.onclick = e => { if (e.target === modal) modal.style.display = "none"; };
    document.body.appendChild(modal);
  }
  modal.style.display = "flex";

  const condSel = h("select", { style: "width:100%;font-size:15px;padding:9px;border-radius:8px;font-weight:700;margin-top:4px" },
    opts([
      ["waspada", "WASPADA — Kenaikan debit air / potensi genangan banjir"],
      ["meluap", "MELUAP — Air sungai meluap deras / masuk permukiman (Darurat)"]
    ], "waspada")
  );

  const noteInput = h("textarea", {
    style: "width:100%;min-height:75px;padding:8px;border-radius:8px;font-size:13px;margin-top:4px",
    placeholder: "Catatan verifikasi pos pantau (opsional, mis. hasil cek visual di pos)"
  });

  const locDisplay = r.location_name || r.title || `Koordinat ${r.lat.toFixed(5)}, ${r.lng.toFixed(5)}`;
  const condsDisplay = r.conditions && r.conditions.length ? r.conditions.map(lab).join(", ") : "Kenaikan debit air";

  const confirmBtn = h("button", {
    class: "danger",
    style: "width:100%;margin-top:14px;padding:11px 16px;font-size:14px;font-weight:700",
    onclick: act(async () => {
      confirmBtn.disabled = true;
      try {
        await api("POST", `/reports/${r.id}/verify`, {
          note: noteInput.value.trim() || null,
          condition: condSel.value
        });
        toast("Laporan diverifikasi & Peringatan bencana disiarkan ke semua role dan Telegram!");
        modal.style.display = "none";
        await after();
      } finally {
        confirmBtn.disabled = false;
      }
    }, "Laporan diterima & Peringatan darurat disiarkan")
  }, "📢 Konfirmasi Terima & Siarkan Peringatan Bencana");

  modal.replaceChildren(
    h("div", { class: "card", style: "max-width:520px;width:100%;padding:22px;background:#fff;border-radius:14px;box-shadow:0 12px 36px rgba(0,0,0,.35)" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:12px" },
        h("h3", { style: "margin:0;color:var(--navy);font-size:18px" }, `Terima Laporan Banjir #${r.id}`),
        h("button", { class: "ghost small", style: "font-size:20px;padding:2px 8px", onclick: () => { modal.style.display = "none"; } }, "✕")
      ),
      h("div", { style: "background:#f8fafc;padding:10px 14px;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:12px;font-size:13px" },
        h("div", {}, h("b", {}, "Judul Laporan: "), r.title || "Laporan Banjir"),
        h("div", { style: "margin-top:4px" }, h("b", {}, "Lokasi Kejadian: "), h("span", { style: "color:var(--teal);font-weight:700" }, locDisplay)),
        h("div", { style: "margin-top:4px" }, h("b", {}, "Kondisi dari Warga: "), condsDisplay),
        r.description ? h("div", { style: "margin-top:4px;color:#475569" }, h("b", {}, "Deskripsi: "), r.description) : null
      ),
      field("Tetapkan Status Kondisi Bencana", condSel),
      field("Catatan Pos Pantau (Opsional)", noteInput),
      h("div", { class: "notice warn", style: "margin-top:10px;font-size:12px" },
        "📢 Penetapan status WASPADA atau MELUAP otomatis mengirimkan peringatan darurat bencana di lokasi ini ke seluruh role aplikasi serta bot Telegram."
      ),
      confirmBtn
    )
  );
}

function openRejectReportModal(r, after) {
  const reason = prompt(`Alasan menolak laporan #${r.id} dari warga (wajib):`);
  if (reason === null) return;
  if (!reason.trim() || reason.trim().length < 3) {
    alert("Alasan penolakan laporan minimal 3 karakter.");
    return;
  }
  act(async () => {
    await api("POST", `/reports/${r.id}/reject`, { reason: reason.trim() });
    toast("Laporan ditolak.");
    await after();
  }, "Laporan ditolak")();
}

// ---------- Laporan (koordinator & pos pantau) ----------
function reportsTable(rows, after) {
  const photo = async (r, cell) => {
    const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
    cell.replaceChildren(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto" }));
  };
  return table([
    { label: "#", key: "id" },
    { label: "Laporan", render: r => [
      h("b", { style: "color:var(--navy);font-size:14px" }, r.title || "Laporan Banjir"),
      " ",
      simBadge(r.source_mode === "simulation"),
      r.location_name ? h("div", { style: "font-size:13px;font-weight:700;color:var(--teal);margin:2px 0" }, "📍 " + r.location_name) : null,
      r.conditions && r.conditions.length ? h("div", { style: "display:flex;flex-wrap:wrap;gap:4px;margin:4px 0" }, r.conditions.map(c => badge(lab(c), "b-warn"))) : null,
      h("div", { style: "margin:4px 0" }, r.description),
      h("div", { class: "muted small-text" }, `${r.lat.toFixed(5)}, ${r.lng.toFixed(5)} · pelapor #${r.reporter_id} · ${lab(r.source)} · ${fmt(r.received_at)}`)
    ] },
    { label: "Status", render: r => [badge(lab(r.status), r.status === "terverifikasi" ? "b-ok" : r.status === "ditolak" ? "b-bad" : "b-info"), r.duplicate_of ? h("div", { class: "muted small-text" }, "duplikat #" + r.duplicate_of) : null, r.status_reason ? h("div", { class: "muted small-text" }, r.status_reason) : null] },
    { label: "Skor", render: r => [h("b", {}, r.score), r.flags.length ? h("div", {}, r.flags.map(f => badge(f.replaceAll("_", " "), "b-bad"))) : null,
      h("details", {}, h("summary", {}, "faktor"), r.score_factors.map(f => h("div", { class: "factor" }, `${f.poin >= 0 ? "+" : ""}${f.poin} ${f.faktor}: ${f.keterangan}`)))] },
    { label: "Foto", render: r => { const c = h("span"); if (r.has_photo) c.append(h("button", { class: "sec small", onclick: act(() => photo(r, c)) }, "Lihat")); else c.append("-"); return c; } },
    { label: "Aksi", render: r => ["diterima", "duplikat"].includes(r.status) ? h("div", { class: "btns" },
      h("button", {
        class: "small",
        style: "background:#0f9d6b;border-color:#0f9d6b;color:#fff;font-weight:700",
        onclick: () => openAcceptReportModal(r, after)
      }, "Terima"),
      h("button", {
        class: "danger small",
        style: "font-weight:700",
        onclick: () => openRejectReportModal(r, after)
      }, "Tolak")
    ) : r.status === "terverifikasi" ? badge("TERVERIFIKASI", "b-ok") : r.status === "ditolak" ? badge("DITOLAK", "b-bad") : "-" },
  ], rows, "Tidak ada laporan.");
}

function openBroadcastModal(defaultMsg = "") {
  let modal = document.getElementById("broadcast-modal");
  if (!modal) {
    modal = h("div", {
      id: "broadcast-modal",
      style: "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(11,58,110,.65);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)"
    });
    modal.onclick = (e) => { if (e.target === modal) modal.style.display = "none"; };
    document.body.appendChild(modal);
  }

  const msgInput = h("textarea", {
    style: "width:100%;min-height:95px;font-size:14px;padding:8px;border-radius:8px",
    placeholder: "Contoh: STATUS WASPADA BANJIR: Ketinggian air sungai meluap di DAS Cikapundung. Warga bantaran sungai diimbau segera evakuasi ke shelter terdekat."
  }, defaultMsg);

  const levelSel = h("select", {}, opts([["waspada", "WASPADA (Kuning)"], ["siaga", "SIAGA (Oranye)"], ["evakuasi", "EVAKUASI / BAHAYA (Merah)"]], "waspada"));

  const chkTelegram = h("input", { type: "checkbox", checked: true, disabled: true });
  const chkSMS = h("input", { type: "checkbox", checked: true, disabled: true });

  const sendBtn = h("button", {
    class: "danger",
    onclick: act(async () => {
      const text = msgInput.value.trim();
      if (!text || text.length < 5) throw new Error("Tuliskan pesan pengumuman minimal 5 karakter");
      await api("POST", "/alerts/broadcast", {
        message: text,
        level: levelSel.value,
        region_id: me.region_id
      });
      toast("Pengumuman darurat berhasil disiarkan ke Telegram & SMS!");
      modal.style.display = "none";
      await reload();
    }, "Pengumuman disiarkan")
  }, "📢 Kirim Siaran Sekarang");

  modal.replaceChildren(
    h("div", { class: "card", style: "max-width:540px;width:100%;padding:22px;background:#fff;border-radius:14px;box-shadow:0 12px 36px rgba(0,0,0,.3)" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;border-bottom:1px solid var(--line);padding-bottom:10px" },
        h("h3", { style: "margin:0;color:var(--navy);font-size:18px" }, "📢 Siarkan Pengumuman Darurat"),
        h("button", { class: "ghost small", style: "font-size:20px;padding:2px 8px", onclick: () => { modal.style.display = "none"; } }, "✕")
      ),
      h("p", { class: "muted small-text" }, "Pengumuman darurat ini akan disiarkan ke seluruh role (Warga, Tim SAR, Koordinator Daerah, Pos Pantau) serta diteruskan ke Bot Telegram dan SMS otomatis."),
      field("Tingkat Level Bahaya", levelSel),
      field("Pesan Pengumuman Darurat", msgInput),
      h("div", { style: "margin:10px 0" },
        h("p", { class: "muted small-text", style: "margin-bottom:4px;font-weight:700" }, "Kanal Distribusi Otomatis:"),
        h("label", { class: "chk", style: "display:inline-block;margin-right:16px" }, chkTelegram, "Bot Telegram Resmi"),
        h("label", { class: "chk", style: "display:inline-block" }, chkSMS, "SMS Broadcast ke Warga & Responders")
      ),
      h("div", { class: "btns", style: "justify-content:flex-end;margin-top:16px" },
        h("button", { class: "sec", onclick: () => { modal.style.display = "none"; } }, "Batal"),
        sendBtn
      )
    )
  );
  modal.style.display = "flex";
  msgInput.focus();
}

async function viewReports(box) {
  const [st, stRows, weather] = await Promise.all([
    h("select", {}, opts([["", "Semua status"], ["diterima", "Diterima"], ["terverifikasi", "Terverifikasi"], ["ditolak", "Ditolak"], ["duplikat", "Duplikat"]], store.get("rw_rep_status", ""))),
    api("GET", "/stations/live").catch(() => []),
    api("GET", "/weather/live").catch(() => null)
  ]);
  st.onchange = () => { store.set("rw_rep_status", st.value); reload(); };
  const rows = await api("GET", "/reports?limit=200" + (st.value ? "&status=" + st.value : ""));

  box.append(
    h("div", { style: "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:12px" },
      h("h2", { style: "margin:0" }, me.role === "pos_pantau" ? "Laporan Masuk & Verifikasi Bencana" : "Laporan Masuk"),
      h("button", {
        class: "danger",
        style: "display:inline-flex;align-items:center;gap:6px",
        onclick: () => openBroadcastModal()
      }, "📢 Siarkan Pengumuman Darurat (Telegram & SMS)")
    )
  );

  // Card Pencocokan Sensor & Cuaca untuk Verifikasi
  box.append(
    h("div", { class: "card", style: "background:linear-gradient(135deg,#f0fdf4,#e0f2fe);border:1px solid #bae6fd;margin-bottom:16px" },
      h("b", { style: "color:var(--navy);font-size:15px;display:block;margin-bottom:4px" }, "🔍 Pencocokan Sensor TMA & Cuaca Terkini (Bandung)"),
      h("div", { class: "muted small-text" },
        weather ? `Hujan: ${weather.rain_mm || 0} mm/jam (${weather.weather_desc || "Normal"}) · Suhu: ${weather.temperature_c || 28}°C · Kelembapan: ${weather.humidity_percent || 70}%` : "Data cuaca Bandung terkini"
      ),
      h("div", { style: "display:flex;gap:10px;flex-wrap:wrap;margin-top:8px" },
        stRows.slice(0, 5).map(s => h("span", { style: "font-size:12px;background:#fff;padding:3px 8px;border-radius:6px;border:1px solid #cbd5e1" },
          h("b", {}, s.name + ": "),
          `${s.latest?.level_cm ?? "—"} cm `,
          badge((s.current_condition || s.status || "normal").toUpperCase(), s.status === "bahaya" || s.current_condition === "meluap" ? "b-bad" : s.status === "waspada" ? "b-warn" : "b-ok")
        ))
      )
    )
  );

  box.append(
    h("div", { class: "notice" }, "Skor hanya alat bantu prioritas, bukan bukti. Cocokkan laporan warga dengan sensor TMA pos pantau dan cuaca sebelum verifikasi & siaran darurat."),
    h("div", { class: "row", style: "max-width:300px" }, field("Filter Status", st)),
    h("div", { class: "card" }, reportsTable(rows, reload))
  );
}

// ---------- Warga (koordinator) ----------
async function viewResidents(box, ctx) {
  const [sum, queue, regions] = await Promise.all([api("GET", "/residents/summary"), api("GET", "/help-requests"), api("GET", "/regions")]);
  const q = h("input", { placeholder: "cari nama" });
  const vul = h("select", {}, opts([["", "Semua"], ["true", "Hanya rentan"], ["false", "Non-rentan"]]));
  const stf = h("select", {}, opts([["", "Semua status"], ...["belum_terkonfirmasi", "aman_mandiri", "aman_terverifikasi", "butuh_bantuan", "dalam_penanganan", "dalam_perjalanan", "tiba_di_titik_aman", "tidak_dapat_dihubungi"].map(k => [k, LABEL[k]])]));
  const list = h("div"), detail = h("div");
  const load = async () => {
    const qs = new URLSearchParams();
    if (q.value) qs.set("q", q.value); if (vul.value) qs.set("vulnerable", vul.value); if (stf.value) qs.set("status", stf.value);
    const rows = await api("GET", "/residents?" + qs);
    list.replaceChildren(table([
      { label: "Nama & Keluarga", render: r => [
        h("b", {}, r.name),
        r.has_smartphone ? "" : " ",
        r.has_smartphone ? null : badge("tanpa HP", "b-warn"),
        r.address_note ? h("div", { class: "muted small-text" }, "🏠 " + r.address_note) : null
      ] },
      { label: "Kerentanan", render: r => r.vulnerability.length ? r.vulnerability.map(v => badge(v, "b-bad")) : "-" },
      { label: "Status", render: r => [h("b", {}, lab(r.latest_status)), r.latest_status_source ? h("div", { class: "muted small-text" }, `${r.latest_status_source} · ${fmt(r.latest_status_at)}`) : null] },
      { label: "Lokasi", render: r => r.last_lat != null ? "terkini " + fmt(r.last_location_at) : r.home_lat != null ? "rumah" : "-" },
      { label: "", render: r => h("div", { class: "btns" },
        h("button", { class: "small no-print", onclick: act(() => open(r.id)) }, "Detail"),
        r.latest_status === "butuh_bantuan" || r.latest_status === "belum_terkonfirmasi" ? h("button", { class: "teal small no-print", onclick: () => { location.hash = "#prioritas"; } }, "Ajukan SAR") : null
      ) }], rows));
  };
  const open = async id => {
    const [r, hist] = await Promise.all([api("GET", `/residents/${id}`), api("GET", `/residents/${id}/statuses`)]);
    const status = h("select", {}, opts(["butuh_bantuan", "dalam_penanganan", "dalam_perjalanan", "tiba_di_titik_aman", "aman_terverifikasi", "tidak_dapat_dihubungi", "belum_terkonfirmasi"]));
    const source = h("select", {}, opts(["koordinator", "buddy", "keluarga", "petugas"]));
    const need = h("select", {}, opts(["evakuasi", "medis", "logistik", "lainnya"]));
    const note = h("input", { placeholder: "Catatan / metode verifikasi / upaya kontak" });
    detail.replaceChildren(h("div", { class: "card accent" },
      h("h3", {}, r.name, " ", badge(lab(r.latest_status), "b-info")),
      h("p", { class: "muted small-text" }, "Detail sensitif ini dicatat di audit log setiap dibuka."),
      h("p", {}, `Rentan: ${r.vulnerability.join(", ") || "-"} · Smartphone: ${r.has_smartphone ? "ya" : "tidak"} · Consent: ${r.consent ? "ya" : "tidak"}`),
      h("p", {}, "Catatan bantuan: ", r.assistance_notes || "-"), h("p", {}, `Pendamping: ${r.buddy_name || "-"} ${r.buddy_phone || ""}`),
      h("h3", {}, "Catat status (termasuk warga tanpa smartphone)"),
      h("div", { class: "row" }, field("Status", status), field("Sumber", source), field("Jenis bantuan", need)),
      field("Catatan", note),
      h("button", {
        onclick: act(async () => {
          await api("POST", `/residents/${id}/status`, { status: status.value, source: source.value, need_type: status.value === "butuh_bantuan" ? need.value : null, note: note.value || null });
          await open(id); await load();
        }, "Status dicatat"),
      }, "Simpan status"),
      h("h3", { style: "margin-top:14px" }, "Riwayat status"), table([
        { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Status", render: x => lab(x.status) },
        { label: "Sumber", key: "source" }, { label: "Oleh", render: x => "user #" + x.updated_by }, { label: "Catatan", render: x => x.note || "-" }], hist)));
    detail.scrollIntoView({ behavior: "smooth" });
  };
  [q, vul, stf].forEach(el => el.addEventListener("change", load));
  q.addEventListener("input", () => { clearTimeout(q._t); q._t = setTimeout(load, 300); });
  box.append(h("h2", {}, "Data Warga & Status Keselamatan"),
    h("div", { class: "grid" }, Object.entries(sum.by_status).map(([k, n]) => h("div", { class: "stat", style: `--c:${k === "butuh_bantuan" ? "#dc2626" : k.startsWith("aman") || k === "tiba_di_titik_aman" ? "#0f9d6b" : "#64748b"}` }, h("b", {}, n), h("span", {}, lab(k))))),
    h("div", { class: "card" }, h("h3", {}, "Antrean butuh bantuan (warga rentan didahulukan)"), table([
      { label: "Warga", render: x => x.resident.name }, { label: "Rentan", render: x => x.is_vulnerable ? badge("RENTAN", "b-bad") : "-" },
      { label: "Kebutuhan", render: x => x.need_type || "-" }, { label: "Sumber", key: "source" }, { label: "Sejak", render: x => fmt(x.requested_at) },
      { label: "", render: x => h("button", { class: "small no-print", onclick: act(() => open(x.resident.id)) }, "Tangani") }], queue, "Tidak ada permintaan bantuan.")),
    h("div", { class: "card" }, h("div", { class: "row no-print" }, field("Cari", q), field("Kerentanan", vul), field("Status", stf), h("button", { class: "sec", onclick: () => window.print() }, "Cetak daftar")), list),
    detail);
  await load();
  const f = { name: h("input"), phone: h("input"), familyHead: h("input", { placeholder: "Nama Kepala Keluarga / No KK" }), familyCount: h("input", { type: "number", min: 1, value: 1, placeholder: "Jumlah jiwa" }), notes: h("textarea"), buddy: h("input"), buddyPhone: h("input"), consent: h("input", { type: "checkbox" }), smart: h("input", { type: "checkbox", checked: true }),
    lat: h("input", { type: "number", step: "any" }), lng: h("input", { type: "number", step: "any" }) };
  const region = h("select", {}, regionOptions(regions, me.region_id, ["rt", "rw"]));
  const vulBox = ["lansia", "disabilitas", "anak", "sakit", "hamil", "tinggal_sendiri", "lainnya"].map(v => ({ v, c: h("input", { type: "checkbox" }) }));
  box.append(h("details", { class: "card no-print" }, h("summary", {}, "Tambah data warga & keluarga"),
    h("div", { class: "row" }, field("Nama Warga", f.name), field("Wilayah (RT/RW)", region), field("Telepon", f.phone)),
    h("div", { class: "row" }, field("Data Keluarga / Kepala KK", f.familyHead), field("Jumlah Anggota Keluarga (Jiwa)", f.familyCount)),
    h("label", { class: "chk" }, f.smart, "Memiliki smartphone"),
    h("p", { class: "muted small-text", style: "margin-bottom:0" }, "Kerentanan (Prioritas Evakuasi: Lansia, Balita/Anak, Disabilitas, Sakit, Hamil):"), vulBox.map(x => h("label", { class: "chk", style: "display:inline-block;margin-right:14px" }, x.c, x.v.replaceAll("_", " "))),
    field("Catatan bantuan / kerentanan", f.notes), h("div", { class: "row" }, field("Pendamping (buddy)", f.buddy), field("Telepon pendamping", f.buddyPhone)),
    h("p", { class: "muted small-text" }, "Lokasi rumah — ketuk peta:"), h("div", { id: "resmap", class: "map", style: "height:240px" }), h("div", { class: "row" }, field("Lat rumah", f.lat), field("Lng rumah", f.lng)),
    h("label", { class: "chk" }, f.consent, "Warga/keluarga menyetujui data kerentanan & lokasi disimpan (wajib bila ada data kerentanan)"),
    h("button", {
      onclick: act(async () => {
        const famStr = f.familyHead.value.trim() ? `[KK: ${f.familyHead.value.trim()} (${f.familyCount.value || 1} org)] ` : "";
        await api("POST", "/residents", {
          name: f.name.value,
          region_id: Number(region.value),
          phone: f.phone.value || null,
          has_smartphone: f.smart.checked,
          address_note: famStr ? famStr.trim() : null,
          vulnerability: vulBox.filter(x => x.c.checked).map(x => x.v),
          assistance_notes: f.notes.value || null,
          buddy_name: f.buddy.value || null,
          buddy_phone: f.buddyPhone.value || null,
          consent: f.consent.checked,
          home_lat: num(f.lat.value),
          home_lng: num(f.lng.value)
        });
        await reload();
      }, "Data warga disimpan"),
    }, "Simpan")));
  ctx.post(() => {
    const map = newMap($("#resmap"));
    let pin = null;
    if (map) map.on("click", e => { f.lat.value = e.latlng.lat.toFixed(6); f.lng.value = e.latlng.lng.toFixed(6); pin ? pin.setLatLng(e.latlng) : (pin = L.marker(e.latlng, { icon: dotIcon("#0a64b8") }).addTo(map)); });
  });
}

// ---------- Cuaca & aturan ----------
async function viewWeather(box) {
  const [weather, rules, regions] = await Promise.all([api("GET", "/weather"), api("GET", "/rules"), api("GET", "/regions")]);
  const region = h("select", {}, regionOptions(regions, me.region_id, ["kelurahan", "rw", "rt"]));
  const active = h("input", { type: "checkbox", checked: true });
  const desc = h("input", { value: "Peringatan hujan lebat BMKG" });
  const src = h("input", { value: "BMKG (input manual)" });
  const sim = h("input", { type: "checkbox" });
  box.append(h("h2", {}, "Cuaca & Aturan"),
    h("div", { class: "notice" }, "Cuaca hanya faktor pendukung (tidak pernah bukti tunggal banjir). Integrasi BMKG otomatis belum ada; isi manual dari kanal resmi BMKG, atau simulasi."),
    h("div", { class: "cols" },
      h("div", { class: "card" }, h("h3", {}, "Konteks cuaca saat ini"), table([
        { label: "Wilayah", render: w => "#" + w.region_id }, { label: "Aktif", render: w => w.is_active ? badge("AKTIF", "b-warn") : "Tidak" },
        { label: "Keterangan", render: w => w.description }, { label: "Sumber", render: w => [w.source, " ", simBadge(w.source_mode === "simulation")] },
        { label: "Diperbarui", render: w => fmt(w.updated_at) }], weather, "Belum ada.")),
      h("div", { class: "card" }, h("h3", {}, "Atur konteks cuaca"),
        field("Wilayah", region), field("Keterangan", desc), field("Sumber", src),
        h("label", { class: "chk" }, active, "Peringatan cuaca aktif"), h("label", { class: "chk" }, sim, "Data simulasi (hanya dihitung untuk kejadian simulasi)"),
        h("button", {
          onclick: act(async () => {
            await api("PUT", "/weather", { region_id: Number(region.value), is_active: active.checked, description: desc.value, source: src.value, source_mode: sim.checked ? "simulation" : "real" });
            await reload();
          }, "Konteks cuaca disimpan"),
        }, "Simpan"))),
    h("div", { class: "card" }, h("h3", {}, "Parameter aturan eskalasi (asumsi untuk diuji)"),
      rules.map(r => h("details", {}, h("summary", {}, `${r.hazard.toUpperCase()}${r.is_default ? " (default)" : ""}`),
        h("pre", { class: "msg" }, JSON.stringify(r.params, null, 2)), h("p", { class: "muted small-text" }, r.note)))));
}

// ---------- Admin ----------
async function viewAdmin(box) {
  const [users, regions, rules, logs] = await Promise.all([api("GET", "/users"), api("GET", "/regions"), api("GET", "/rules"), api("GET", "/audit-logs?limit=100")]);
  const f = { u: h("input"), n: h("input"), p: h("input", { type: "password" }), tg: h("input", { placeholder: "chat ID (opsional)" }) };
  const role = h("select", {}, opts([
    ["warga", "Warga"],
    ["koordinator", "Koordinator Daerah"],
    ["pos_pantau", "Petugas Pos Pantau"],
    ["tim_sar", "Tim SAR"],
    ["admin", "Admin Sistem"]
  ]));
  const region = h("select", {}, regionOptions(regions, me.region_id));
  box.append(h("h2", {}, "Kelola Pengguna & Akun"),
    h("div", { class: "card" }, h("h3", {}, "Kelola Akun Pengguna"), table([
      { label: "Username", key: "username" }, { label: "Nama", key: "name" }, { label: "Peran", render: u => ROLE_LABEL[u.role] || u.role }, { label: "Wilayah", render: u => "#" + u.region_id },
      { label: "Aktif", render: u => u.is_active ? badge("AKTIF", "b-ok") : badge("NONAKTIF", "b-bad") },
      { label: "", render: u => u.is_active && u.id !== me.id ? h("button", { class: "danger small", onclick: act(async () => { const reason = prompt("Alasan menonaktifkan " + u.username + ":"); if (!reason) throw new Error("batal"); await api("POST", `/users/${u.id}/deactivate`, { reason }); await reload(); }) }, "Nonaktifkan") : "" }], users),
      h("details", {}, h("summary", {}, "Buat Akun Pengguna Baru"),
        h("div", { class: "row" }, field("Username (a-z 0-9 _ .)", f.u), field("Nama", f.n), field("Password (min 8)", f.p)),
        h("div", { class: "row" }, field("Peran", role), field("Wilayah", region), field("Telegram chat ID", f.tg)),
        h("button", { onclick: act(async () => { await api("POST", "/users", { username: f.u.value, name: f.n.value, password: f.p.value, role: role.value, region_id: Number(region.value), telegram_chat_id: f.tg.value || null }); await reload(); }, "Akun berhasil dibuat") }, "Simpan Akun"))),
    h("div", { class: "card" }, h("h3", {}, "Aturan Eskalasi Siaga Bencana (JSON)"), rules.map(r => {
      const ta = h("textarea", { style: "min-height:240px;font-family:monospace;font-size:13px" }); ta.value = JSON.stringify(r.params, null, 2);
      return h("details", {}, h("summary", {}, r.hazard.toUpperCase()), ta,
        h("button", { onclick: act(async () => { await api("PUT", `/rules/${r.hazard}`, JSON.parse(ta.value)); await reload(); }, "Aturan disimpan") }, "Simpan aturan"));
    })),
    h("div", { class: "card" }, h("h3", {}, "Audit Log Sistem (100 Terakhir)"), table([
      { label: "Waktu", render: l => fmt(l.created_at) }, { label: "Pelaku", render: l => l.actor_id ? "user #" + l.actor_id : "sistem" }, { label: "Aksi", key: "action" },
      { label: "Objek", render: l => `${l.entity_type} ${l.entity_id ?? ""}` }, { label: "Alasan", render: l => l.reason || "-" }], logs)));
}

boot();
