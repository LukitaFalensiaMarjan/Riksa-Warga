import { DEMO_CENTER, lab } from "../config.js";
import { h } from "./dom.js";
import { cfg } from "../state.js";

export let cleanups = [];
export const stopMaps = () => { cleanups.forEach(f => { try { f(); } catch { /* sudah dilepas */ } }); cleanups = []; };
export const tip = text => h("span", {}, text);  // elemen, bukan string HTML: aman dari XSS di tooltip Leaflet

export function newMap(el, center, zoom = 15) {
  if (!window.L) { el.textContent = "Peta tidak dapat dimuat. Buka sekali saat online agar tersimpan untuk offline."; return null; }
  const map = L.map(el).setView(center || DEMO_CENTER, zoom);
  // warga: Esri World Street Map (tanpa kunci API, palet paling dekat Google Maps); bila gagal dimuat, kembali ke ubin server
  const esri = document.body.classList.contains("tw");
  const base = L.tileLayer(esri ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}" : cfg.tile_url,
    { maxZoom: 19, attribution: esri ? "Tiles © Esri" : cfg.tile_attribution, crossOrigin: true }).addTo(map);
  if (esri) {
    let bad = 0;
    base.on("tileerror", () => {
      if (++bad !== 4) return;
      map.removeLayer(base);
      L.tileLayer(cfg.tile_url, { maxZoom: 19, attribution: cfg.tile_attribution, crossOrigin: true }).addTo(map);
    });
  }
  cleanups.push(() => map.remove());
  setTimeout(() => map.invalidateSize(), 80);
  return map;
}
export const pinIcon = (color, glyph, pulse = false) => L.divIcon({
  className: "", html: `<div class="pin${pulse ? " pulse" : ""}" style="background:${color}"><span>${glyph}</span></div>`,
  iconSize: [30, 30], iconAnchor: [15, 30], tooltipAnchor: [0, -26],
});
export const dotIcon = color => L.divIcon({ className: "", html: `<div class="dotpin" style="background:${color}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
export const meIcon = () => L.divIcon({ className: "", html: '<div class="me-dot"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
export function addShelters(map, shelters) {
  shelters.forEach(s => L.marker([s.lat, s.lng], { icon: pinIcon(s.is_verified ? (s.status === "penuh" ? "#94a3b8" : "#0f9d6b") : "#a3b8a9", "S") })
    .addTo(map).bindTooltip(tip(`Shelter: ${s.name} · ${lab(s.status)} · ${s.occupancy || 0}/${s.capacity ?? "?"} orang${s.is_verified ? "" : " · BELUM terverifikasi"}`)));
}
export function addHazards(map, hazards) {
  hazards.forEach(x => L.marker([x.lat, x.lng], { icon: pinIcon("#b91c1c", "!") })
    .addTo(map).bindTooltip(tip(`${lab(x.kind)}${x.note ? ": " + x.note : ""}`)));
}
export const ROUTE_STYLE = {
  terverifikasi: { color: "#0f9d6b", weight: 6, opacity: .9 },
  dilaporkan_dapat_dilalui: { color: "#0e7c86", weight: 5, dashArray: "8 6" },
  belum_diverifikasi: { color: "#64748b", weight: 4, dashArray: "4 6" },
  ditutup: { color: "#dc2626", weight: 5, dashArray: "2 8" },
};
export function addRoutes(map, routes) {
  routes.forEach(r => L.polyline(r.points, ROUTE_STYLE[r.status]).addTo(map).bindTooltip(tip(`Rute resmi: ${r.name} — ${lab(r.status)}`)));
}
export const legend = items => h("div", { class: "legend" }, items.map(([c, t]) => h("span", {}, h("i", { style: `background:${c}` }), t)));
