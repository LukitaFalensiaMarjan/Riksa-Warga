import { LEVEL_COLOR, LEVEL_RANK, lab } from "../../config.js";
import { api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { addHazards, addRoutes, addShelters, dotIcon, legend, newMap, pinIcon, tip } from "../../lib/map.js";
import { store } from "../../lib/store.js";
import { lvl, simBadge, table } from "../../lib/ui.js";
import { me } from "../../state.js";
import { SKY, ago, svgBox } from "../warga/kit.js";

// ---------- Dashboard koordinator ----------
const pct = (n, total) => (total ? Math.round(n / total * 100) : 0);
const STATUS_C = { normal: "#17a98a", waspada: "#d97706", bahaya: "#dc2626" };

export async function viewDashboard(box, ctx) {
  const [d, shelters, tasks, hazards, routes, reps] = await Promise.all([api("GET", "/dashboard"), api("GET", "/shelters"), api("GET", "/tasks?active=true"),
    api("GET", "/road-conditions"), api("GET", "/evacuation-routes"), api("GET", "/reports?limit=200").catch(() => [])]);
  const by = d.residents.by_status;
  const total = Object.values(by).reduce((a, b) => a + b, 0), safe = by.aman_mandiri + by.aman_terverifikasi;
  const top = d.incidents.reduce((m, i) => LEVEL_RANK[i.level] > (LEVEL_RANK[m?.level] || 0) ? i : m, null);
  const first = me?.name || "Koordinator";

  // ---- banner sapaan + kejadian tertinggi ----
  const pill = h("a", { class: "d-pill" + (top ? " l-" + top.level : ""), href: top ? "#incidents" : "#reports", style: top ? `--lc:${LEVEL_COLOR[top.level]}` : "" },
    h("span", { class: "d-pill-ico" }, icon(top ? "alert" : "check")),
    h("span", { class: "d-pill-t" },
      h("small", {}, top ? `${top.is_simulation ? "SIMULASI · " : ""}Kejadian aktif tertinggi · ${lab(top.verification)}` : "Kondisi wilayah"),
      h("b", {}, top ? `${top.level.toUpperCase()} ${top.hazard.toUpperCase()} — #${top.id}` : "Tidak ada kejadian aktif"),
      top ? h("em", {}, `${top.unique_reporters} pelapor unik · laporan terakhir ${fmt(top.last_report_at)}${top.pending_level ? ` · usulan ${top.pending_level.toUpperCase()} otomatis ${fmt(top.pending_deadline)}` : ""}`) : null),
    icon("arrow"));
  const banner = h("div", { class: "d-banner" }, svgBox("d-sky", SKY),
    h("div", { class: "d-sys" }, h("span", { class: "d-dot" + (navigator.onLine ? "" : " off") }), h("span", {}, h("small", {}, navigator.onLine ? "Sistem online" : "Offline"), h("b", {}, fmt(d.generated_at)))),
    h("h1", {}, `Selamat datang, ${first}! 👋`), h("p", {}, "Pantau situasi dan kelola respons bencana secara real-time"), pill);

  // ---- empat kartu ringkasan (angka nyata, bar = porsi dari total warga) ----
  const kstat = (cls, ic, n, label, sub, p) => h("div", { class: "k-stat " + cls },
    h("span", { class: "k-ico" }, icon(ic)), h("div", {}, h("b", {}, n), h("small", {}, label)), h("em", {}, sub),
    p != null ? h("div", { class: "k-bar" }, h("i", { style: `width:${p}%` })) : null);
  const stats = h("div", { class: "k-stats" },
    kstat("k-blue", "warga", total, "Total warga terpantau", `${by.belum_terkonfirmasi} belum terkonfirmasi`, 100 - pct(by.belum_terkonfirmasi, total)),
    kstat("k-green", "check", safe, "Warga aman", `${pct(safe, total)}% dari total`, pct(safe, total)),
    kstat("k-red", "sos", d.help_queue, "Butuh bantuan", d.help_queue ? "perlu penanganan segera" : "tidak ada antrean", pct(d.help_queue, total)),
    kstat("k-amber", "kejadian", d.incidents.length, "Kejadian aktif", `${d.reports_24h.total} laporan dalam 24 jam`, null));

  // ---- laporan terbaru (kanan peta) ----
  const recent = [...reps].sort((a, b) => (a.received_at < b.received_at ? 1 : -1)).slice(0, 6);
  const RC = { terverifikasi: "#17a98a", ditolak: "#dc2626", duplikat: "#d97706", diterima: "#1e88f0" };
  const repList = h("div", { class: "card k-reps" },
    h("div", { class: "d-info-h" }, h("h3", {}, icon("inbox"), "Laporan terbaru"), h("a", { class: "d-link", href: "#reports" }, "Lihat semua", icon("arrow"))),
    recent.length ? recent.map(r => h("a", { class: "d-feed", href: "#reports", style: `--lc:${RC[r.status] || "#1e88f0"}` },
      h("span", { class: "d-feed-ico" }, icon("banjir")),
      h("span", { class: "d-feed-t" }, h("b", {}, `Banjir #${r.id}`, simBadge(r.source_mode === "simulation")), h("small", {}, r.description)),
      h("span", { class: "d-feed-time" }, h("span", {}, ago(r.received_at), h("br"), lab(r.status)), h("i")))) : h("p", { class: "muted", style: "padding:14px 0" }, "Belum ada laporan masuk."));

  // ---- status warga (cincin) + pos pantau (tinggi air) ----
  const ring = (label, n, c) => h("div", { class: "k-ring", style: `--c:${c};--p:${pct(n, total)}` }, h("div", {}, h("b", {}, pct(n, total) + "%")), h("span", {}, label), h("small", {}, `${n} / ${total}`));
  const rings = h("div", { class: "card" }, h("h3", {}, icon("warga"), "Status warga"),
    h("div", { class: "k-rings" }, ring("Aman", safe, "#17a98a"), ring("Butuh bantuan", (by.butuh_bantuan || 0) + (by.dalam_penanganan || 0), "#ef5a52"),
      ring("Di titik aman", by.tiba_di_titik_aman, "#1e88f0"), ring("Belum terkonfirmasi", by.belum_terkonfirmasi, "#d97706")),
    h("div", { class: "k-sar" }, icon("tugas"), h("span", {}, h("b", {}, tasks.length), " tugas SAR aktif"), h("a", { class: "d-link", href: "#tugas" }, "Kelola", icon("arrow"))));
  const gauge = s => {
    const lvlcm = s.latest?.level_cm, p = lvlcm != null ? Math.min(100, Math.round(lvlcm / s.danger_cm * 100)) : 0;
    return h("div", { class: "k-gauge", style: `--c:${STATUS_C[s.status] || "#64748b"}` },
      h("div", { class: "k-gauge-h" }, h("b", {}, s.name), h("span", { class: "badge" }, lab(s.status))),
      h("div", { class: "occ" }, h("i", { style: `width:${p}%;background:var(--c)` })),
      h("small", { class: "muted" }, lvlcm != null ? `${lvlcm} cm${s.latest.source_mode === "simulation" ? " (SIM)" : ""} · waspada ${s.warning_cm} · bahaya ${s.danger_cm}` : "Belum ada bacaan"));
  };
  const pos = h("div", { class: "card" }, h("h3", {}, icon("cuaca"), "Pos pantau & cuaca"),
    d.stations.length ? d.stations.map(gauge) : h("p", { class: "muted" }, "Belum ada pos pantau."),
    d.weather.length ? h("div", { class: "k-wx" }, d.weather.map(w => h("div", {}, icon("cuaca"), h("span", {}, w.description, " ", simBadge(w.source_mode === "simulation"))))) : null);

  box.append(h("div", { class: "d-home" }, banner, stats,
    h("div", { class: "k-main" },
      h("div", { class: "card" }, h("h3", {}, icon("peta"), "Peta situasi"),
        legend([["#dc2626", "Kejadian"], ["#64748b", "Laporan"], ["#0f9d6b", "Shelter"], ["#0a64b8", "Pos pantau"], ["#b91c1c", "Bahaya jalan"], ["#7c3aed", "Tugas"]]),
        h("div", { id: "ovmap", class: "map k-map" })), repList),
    h("div", { class: "d-row2 even" }, rings, pos),
    h("div", { class: "card" }, h("h3", {}, icon("kejadian"), "Kejadian aktif"), table([
      { label: "#", key: "id" }, { label: "Jenis", render: i => [i.hazard, " ", simBadge(i.is_simulation)] },
      { label: "Level", render: i => lvl(i.level) }, { label: "Pelapor", key: "unique_reporters" },
      { label: "", render: i => h("a", { href: "#incidents", onclick: () => store.set("rw_open", i.id) }, "Buka") }], d.incidents, "Tidak ada kejadian aktif.")),
    h("div", { class: "card" }, h("h3", {}, icon("alert"), "Peringatan terbaru"), table([
      { label: "Waktu", render: a => fmt(a.created_at) }, { label: "Jenis", key: "kind" },
      { label: "Level", render: a => a.level ? lvl(a.level) : "-" }, { label: "Internal", render: a => a.internal ? "Ya" : "Tidak" },
      { label: "Kejadian", render: a => a.incident_id ? "#" + a.incident_id : "-" }], d.recent_alerts))));
  box.querySelectorAll(".d-home > *").forEach((el, i) => { el.classList.add("rise"); el.style.setProperty("--i", i); });

  ctx.post(() => {
    const map = newMap($("#ovmap"));
    if (!map) return;
    addRoutes(map, routes); addHazards(map, hazards); addShelters(map, shelters);
    reps.forEach(r => L.marker([r.lat, r.lng], { icon: dotIcon(r.status === "ditolak" ? "#cbd5e1" : "#64748b") }).addTo(map).bindTooltip(tip(`Laporan #${r.id} ${r.hazard} (${lab(r.status)})`)));
    d.stations.forEach(s => L.marker([s.lat, s.lng], { icon: pinIcon("#0a64b8", "P") }).addTo(map).bindTooltip(tip(`Pos: ${s.name} (${lab(s.status)})`)));
    tasks.filter(t => t.lat != null).forEach(t => L.marker([t.lat, t.lng], { icon: dotIcon("#7c3aed") }).addTo(map).bindTooltip(tip(`Tugas #${t.id} ${t.task_type} · ${lab(t.status)}`)));
    d.incidents.forEach(i => {
      L.circle([i.lat, i.lng], { radius: i.hazard === "banjir" ? 250 : 150, color: LEVEL_COLOR[i.level], weight: 1, fillOpacity: .12 }).addTo(map);
      L.marker([i.lat, i.lng], { icon: pinIcon(LEVEL_COLOR[i.level], "!", LEVEL_RANK[i.level] >= 3) }).addTo(map).bindTooltip(tip(`Kejadian #${i.id} ${i.hazard} — ${i.level.toUpperCase()}`));
    });
  });
}
