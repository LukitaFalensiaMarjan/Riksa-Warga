import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { fmtDist } from "../../lib/format.js";
import { dist, getPosition, gmaps } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { meIcon, newMap, pinIcon, tip } from "../../lib/map.js";
import { badge } from "../../lib/ui.js";
import { ago } from "../warga/kit.js";

// ---------- Tim SAR: peta menuju semua warga yang butuh bantuan ----------
const GROUP = { dewasa: "dewasa", anak: "anak", balita: "balita", lansia: "lansia" };
const FILTERS = [["semua", "Semua", () => true], ["bahaya", "Zona bahaya", i => i.in_danger], ["rentan", "Rentan", i => i.vulnerability.length], ["kabar", "Belum ada kabar", i => i.unconfirmed]];

function famLine(hh) {
  const c = {}; hh.members.forEach(m => { c[m.age_group] = (c[m.age_group] || 0) + 1; });
  const special = hh.members.filter(m => m.needs.length).length;
  return `Keluarga ${hh.name}: ${hh.members.length} orang (${Object.entries(c).map(([k, n]) => `${n} ${GROUP[k] || k}`).join(", ")})${special ? ` · ${special} berkebutuhan khusus` : ""}`;
}

export async function viewHelpMap(box, ctx) {
  const d = await api("GET", "/sar/help-map");
  let map = null, me = null, filter = "semua", sortNear = false;
  const markers = new Map();
  const list = h("div", { class: "hp-list" }), status = h("small", { class: "muted" });

  const color = i => i.in_danger ? "#dc2626" : i.unconfirmed ? "#64748b" : "#ea580c";
  const near = i => me && i.lat != null ? dist(me, [i.lat, i.lng]) : null;

  function draw() {
    const pass = FILTERS.find(f => f[0] === filter)[2];
    let rows = d.items.filter(pass);
    if (sortNear && me) rows = [...rows].sort((a, b) => (near(a) ?? 1e12) - (near(b) ?? 1e12));
    list.replaceChildren(...(rows.length ? rows.map(i => h("div", { class: "card hp-item" + (i.in_danger ? " danger" : ""), onclick: e => { if (!e.target.closest("a,button") && map && i.lat != null) { map.flyTo([i.lat, i.lng], 17); markers.get(i.resident_id)?.openTooltip(); } } },
      h("div", { class: "hp-top" }, h("b", {}, i.name), h("span", { class: "muted small-text" }, ago(i.requested_at))),
      h("div", { class: "btns", style: "margin:6px 0" },
        i.in_danger ? badge("ZONA BAHAYA", "b-bad") : null, i.unconfirmed ? badge("BELUM ADA KABAR", "b-warn") : badge(`Butuh ${i.need_type || "bantuan"}`, "b-info"),
        i.vulnerability.length ? badge("Rentan: " + i.vulnerability.join(", "), "b-bad") : null, i.has_task ? badge("Sudah ada tugas", "b-ok") : null),
      i.note ? h("div", { class: "muted small-text" }, i.note) : null,
      i.household ? h("div", { class: "hp-fam" }, icon("warga"), famLine(i.household)) : null,
      h("div", { class: "hp-foot" },
        h("span", { class: "muted small-text" }, i.lat == null ? "Lokasi belum diketahui" : `${i.position_kind === "terkini" ? "Lokasi terkini" : "Lokasi rumah"}${near(i) != null ? " · " + fmtDist(near(i)) + " dari Anda" : ""}`),
        i.lat != null ? h("a", { href: gmaps(i.lat, i.lng), target: "_blank", rel: "noopener" }, h("button", { class: "small", type: "button" }, icon("rute"), "Navigasi")) : null)))
      : [h("div", { class: "card w-empty" }, icon("check"), h("h3", {}, "Tidak ada warga di kategori ini"), h("p", {}, d.incident_id ? "Tidak ada warga yang cocok dengan filter." : "Tidak ada kejadian aktif, sehingga belum ada yang dianggap butuh bantuan."))]));
  }
  const chips = FILTERS.map(([k, t, fn]) => h("button", { type: "button", class: "w-chip" + (k === filter ? " on" : ""), onclick: ev => { filter = k; chips.forEach(c => c.classList.toggle("on", c === ev.currentTarget)); draw(); } }, t, h("i", {}, d.items.filter(fn).length)));
  const locate = h("button", { class: "sec small", onclick: act(async () => {
    const p = await getPosition(); me = [p[0], p[1]]; sortNear = true; status.textContent = "Daftar diurutkan dari yang terdekat dengan Anda.";
    if (map) { L.marker(me, { icon: meIcon(), zIndexOffset: 1000 }).addTo(map).bindTooltip(tip("Posisi saya")); }
    draw();
  }) }, icon("gps"), "Urutkan dari posisi saya");

  const inDanger = d.items.filter(i => i.in_danger).length;
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Peta Bantuan"), h("p", {}, d.incident_id ? `${d.items.length} warga butuh bantuan atau belum memberi kabar · ${inDanger} di zona bahaya (±${d.danger_radius_m} m dari kejadian)` : "Tidak ada kejadian aktif saat ini.")),
    h("div", { class: "card" }, h("div", { id: "hpmap", class: "map k-map" }),
      h("div", { class: "legend" }, h("span", {}, h("i", { style: "background:#dc2626" }), "Zona bahaya"), h("span", {}, h("i", { style: "background:#ea580c" }), "Minta bantuan"), h("span", {}, h("i", { style: "background:#64748b" }), "Belum ada kabar"))),
    h("div", { class: "w-chips" }, chips, locate), status, list);
  draw();
  ctx.post(() => {
    map = newMap($("#hpmap"));
    if (!map) return;
    const pts = [];
    d.items.filter(i => i.lat != null).forEach(i => {
      const m = L.marker([i.lat, i.lng], { icon: pinIcon(color(i), i.unconfirmed ? "?" : "!", i.in_danger) }).addTo(map)
        .bindTooltip(tip(`${i.name}${i.in_danger ? " · ZONA BAHAYA" : ""}${i.vulnerability.length ? " · rentan" : ""}`));
      markers.set(i.resident_id, m); pts.push([i.lat, i.lng]);
    });
    if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 16 });
  });
}
