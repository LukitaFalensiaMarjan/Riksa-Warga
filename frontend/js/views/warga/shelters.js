import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { fmtDist } from "../../lib/format.js";
import { bearing, compass, dist, gmaps } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { addShelters, newMap } from "../../lib/map.js";
import { badge, field } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Shelter (warga): kartu + peta, diurutkan dari yang terdekat ----------
export async function viewWargaShelters(box, ctx) {
  const [rows, res] = await Promise.all([api("GET", "/shelters"), api("GET", "/me/resident").catch(() => null)]);
  const from = res?.last_lat != null ? [res.last_lat, res.last_lng] : res?.home_lat != null ? [res.home_lat, res.home_lng] : null;
  const items = rows.map(s => ({ s, d: from ? dist(from, [s.lat, s.lng]) : null, b: from ? bearing(from, [s.lat, s.lng]) : null }))
    .sort((a, b) => (a.d ?? 0) - (b.d ?? 0));
  let filter = "tersedia", map = null;
  const open = it => ["tersedia", "terbatas"].includes(it.s.status);
  const list = h("div", { class: "sh-list" });
  const FILTERS = [["tersedia", "Bisa dipakai", items.filter(open).length], ["semua", "Semua", items.length]];
  const chips = FILTERS.map(([f, t, n]) => h("button", { type: "button", class: "w-chip" + (f === filter ? " on" : ""), onclick: () => { filter = f; chips.forEach((c, i) => c.classList.toggle("on", FILTERS[i][0] === f)); draw(); } }, t, h("i", {}, n)));

  function draw() {
    const shown = items.filter(it => filter === "semua" || open(it));
    list.replaceChildren(...(shown.length ? shown.map(card) : [h("div", { class: "card w-empty", style: "grid-column:1/-1" }, icon("shelter"), h("h3", {}, "Belum ada shelter"), h("p", {}, "Tidak ada shelter terverifikasi yang tersedia saat ini."))]));
  }
  function card({ s, d, b }, i) {
    const pct = s.capacity ? Math.min(100, Math.round((s.occupancy || 0) / s.capacity * 100)) : 0, bar = h("i");
    setTimeout(() => { bar.style.width = pct + "%"; }, 60);
    const el = h("div", {
      class: "card sh rise", style: `--i:${Math.min(i, 8)}`,
      onclick: ev => { if (ev.target.closest("a,button")) return; list.querySelectorAll(".sh").forEach(x => x.classList.toggle("on", x === el)); if (map) { map.flyTo([s.lat, s.lng], 17); $("#shmap").scrollIntoView({ behavior: "smooth", block: "center" }); } },
    },
    h("div", { class: "sh-row" }, h("h4", {}, s.name), badge(lab(s.status), { tersedia: "b-ok", terbatas: "b-warn" }[s.status] || "b-bad")),
    h("div", { class: "muted small-text" }, s.address),
    d != null ? h("div", { class: "sh-d", style: "margin-top:8px" }, icon("pin"), `±${fmtDist(d)} · arah ${compass(b)}`) : null,
    h("div", { class: "occ" + (pct > 85 ? " full" : pct > 60 ? " mid" : "") }, bar),
    h("div", { class: "muted small-text" }, `Terisi ${s.occupancy || 0} dari ${s.capacity ?? "?"} orang${s.capacity ? ` · sisa ${Math.max(0, s.capacity - (s.occupancy || 0))}` : ""}`),
    s.accessibility_note ? h("div", { class: "muted small-text" }, "♿ " + s.accessibility_note) : null,
    h("div", { class: "btns" },
      h("button", { class: "small", onclick: () => { location.hash = "#peta"; } }, "Rute di peta"),
      h("a", { href: gmaps(s.lat, s.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec small", type: "button" }, "Google Maps")),
      s.contact ? h("a", { href: "tel:" + s.contact.replace(/[^\d+]/g, "") }, h("button", { class: "sec small", type: "button" }, "Hubungi")) : null));
    return el;
  }
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Shelter / Titik Aman"), h("p", {}, from ? "Diurutkan dari yang terdekat dengan Anda." : "Hanya titik aman terverifikasi yang ditampilkan.")),
    h("div", { class: "card sh-map" }, h("div", { id: "shmap", class: "map", style: "margin:0" })),
    h("div", { class: "w-chips" }, chips), list);
  draw();
  ctx.post(() => { map = newMap($("#shmap")); if (map) addShelters(map, rows); });
  if (me.role === "tim_sar" && rows.length) {  // Tim SAR mencatat warga yang tiba di shelter
    const pick = h("select", {}, rows.map(s => h("option", { value: s.id }, s.name)));
    const who = h("input", { placeholder: "Nama / rombongan" }), n = h("input", { type: "number", min: 1, value: 1 });
    box.append(h("div", { class: "card", style: "margin-top:16px" }, h("h3", {}, icon("check"), "Catat warga tiba di shelter"),
      h("div", { class: "row" }, field("Shelter", pick), field("Nama", who), field("Jumlah orang", n),
        h("button", { onclick: act(async () => { await api("POST", `/shelters/${pick.value}/checkin`, { name: who.value.trim(), people_count: Number(n.value) }); await reload(); }, "Check-in tercatat") }, "Catat"))));
  }
}
