import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { chart, gauge } from "../../lib/chart.js";
import { h } from "../../lib/dom.js";
import { fmt, num } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { badge, field, opts, regionOptions } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { ago } from "../warga/kit.js";

// ---------- Pos pantau: grafik tinggi air interaktif + input pengamatan ----------
const STATUS_C = { normal: "#17a98a", waspada: "#d97706", bahaya: "#dc2626", data_kedaluwarsa: "#64748b", tidak_ada_data: "#64748b" };
const STATUS_L = { normal: "Normal", waspada: "Waspada", bahaya: "Meluap", data_kedaluwarsa: "Data lama", tidak_ada_data: "Belum ada data" };
const RANGES = [[3, "3 jam"], [6, "6 jam"], [12, "12 jam"], [24, "24 jam"], [72, "3 hari"]];
const COND = { normal: "Normal", naik: "Naik", arus_deras: "Arus deras", meluap: "Meluap" };
const suggest = (v, s) => v >= s.danger_cm ? "meluap" : v >= s.warning_cm ? "naik" : "normal";

let remembered = null, hours = 12;   // pilihan pos dan rentang waktu bertahan setelah simpan/muat ulang

export async function viewStations(box) {
  const stations = await api("GET", "/stations");
  const canInput = ["pos_pantau", "koordinator"].includes(me.role);
  const canCreate = me.role === "koordinator";
  const panel = h("div");
  let current = stations.find(s => s.id === remembered)?.id ?? stations[0]?.id;

  const cards = h("div", { class: "sp-cards" }, stations.map(s => {
    const c = STATUS_C[s.status] || STATUS_C.tidak_ada_data, p = s.latest ? Math.min(100, Math.round(s.latest.level_cm / s.danger_cm * 100)) : 0;
    return h("button", { type: "button", class: "sp-card" + (s.id === current ? " on" : ""), style: `--c:${c}`, "data-id": s.id, onclick: () => { current = remembered = s.id; cards.querySelectorAll(".sp-card").forEach(b => b.classList.toggle("on", +b.dataset.id === s.id)); select(s); } },
      h("span", { class: "sp-top" }, h("b", {}, s.name), h("em", {}, STATUS_L[s.status] || lab(s.status))),
      h("span", { class: "sp-val" }, s.latest ? `${s.latest.level_cm}` : "—", h("small", {}, " cm")),
      h("span", { class: "sp-bar" }, h("i", { style: `width:${p}%` })),
      h("small", { class: "muted" }, `${s.is_upstream ? "Hulu · " : ""}${s.river_name || "Sungai"}${s.latest ? " · " + ago(s.latest.observed_at) : ""}`));
  }));

  async function select(s) {
    const t = await api("GET", `/stations/${s.id}/trend?hours=${hours}`);
    const status = t.status, c = STATUS_C[status] || "#64748b";
    const ch = chart(t.readings, s, { hours }), g = gauge(s), last = t.readings.at(-1);
    g.set(last && !t.stale ? last.level_cm : last?.level_cm ?? null, status);

    const range = h("div", { class: "w-chips" }, RANGES.map(([hr, lbl]) => h("button", { type: "button", class: "w-chip" + (hr === hours ? " on" : ""), onclick: () => { hours = hr; select(s); } }, lbl)));
    const body = [h("div", { class: "sp-head" }, h("div", {}, h("h3", {}, icon("pos"), `${s.name}${s.is_upstream ? " (hulu)" : ""}`), h("small", { class: "muted" }, s.river_name || "Sungai")),
        h("div", { class: "btns" }, h("span", { class: "n-cond", style: `--c:${c}` }, STATUS_L[status] || status), badge("Tren: " + t.direction.replaceAll("_", " "), "b-info"), t.stale ? badge("DATA LAMA", "b-warn") : null)),
      range, h("div", { class: "sp-viz" }, h("div", { class: "sp-chart" }, ch, h("small", { class: "muted" }, "Sentuh atau arahkan kursor pada grafik untuk melihat detail tiap pengamatan. Titik ungu = simulasi.")), g)];

    if (canInput) {
      const level = h("input", { type: "number", min: 0, step: "any", placeholder: "cm", class: "sp-num" });
      const slider = h("input", { type: "range", min: 0, max: Math.round(s.danger_cm * 1.5), step: 1, value: Math.round(s.warning_cm * .5), "aria-label": "Tinggi air (cm)" });
      const cond = h("select", {}, opts(Object.entries(COND).map(([k, v]) => [k, v])));
      const note = h("input", { placeholder: "catatan kondisi daerah (opsional)" });
      const sim = h("input", { type: "checkbox" });
      let manual = false;
      cond.onchange = () => { manual = true; };
      const sync = v => {
        ch.setPreview(v); g.preview(v);
        if (v !== "" && !manual) cond.value = suggest(+v, s);
        zone.textContent = v === "" ? "" : +v >= s.danger_cm ? "Di atas batas bahaya — meluap" : +v >= s.warning_cm ? "Di atas batas waspada" : "Di bawah batas waspada";
        zone.style.color = v === "" ? "" : +v >= s.danger_cm ? "#dc2626" : +v >= s.warning_cm ? "#d97706" : "#17a98a";
      };
      const zone = h("small", { class: "sp-zone" });
      level.oninput = () => { slider.value = level.value; sync(level.value); };
      slider.oninput = () => { level.value = slider.value; sync(slider.value); };
      const quick = [["Normal", Math.round(s.warning_cm * .5)], ["Waspada", s.warning_cm], ["Meluap", s.danger_cm]].map(([t, v]) =>
        h("button", { type: "button", class: "w-chip", onclick: () => { level.value = slider.value = v; manual = false; sync(String(v)); } }, `${t} (${v} cm)`));
      body.push(h("div", { class: "sp-form" }, h("h3", {}, "Input pengamatan tinggi air"),
        h("p", { class: "muted small-text" }, "Geser penggeser atau ketik angkanya. Garis biru putus-putus pada grafik dan bayangan pada tangki menunjukkan pratinjau sebelum disimpan."),
        h("div", { class: "sp-slide" }, level, slider), zone, h("div", { class: "w-chips", style: "margin-top:8px" }, quick),
        h("div", { class: "row" }, field("Kondisi sungai", cond), field("Catatan", note)),
        h("label", { class: "chk" }, sim, "Data simulasi (demo)"),
        h("button", {
          onclick: act(async () => {
            if (level.value === "") throw new Error("Isi tinggi air");
            await api("POST", `/stations/${s.id}/observations`, { level_cm: Number(level.value), river_condition: cond.value, note: note.value || null, source_mode: sim.checked ? "simulation" : "real" });
            await reload();
          }, "Pengamatan tersimpan"),
        }, "Simpan pengamatan")));
    }
    const recent = [...t.readings].reverse().slice(0, 8);
    body.push(h("div", { class: "sp-recent" }, h("h4", {}, "Pengamatan terakhir"), recent.length ? recent.map(r => h("div", { class: "sp-r" }, h("b", {}, `${r.level_cm} cm`), badge(COND[r.river_condition] || r.river_condition, r.river_condition === "normal" ? "b-ok" : r.river_condition === "meluap" ? "b-bad" : "b-warn"),
      h("span", { class: "muted small-text" }, `${fmt(r.observed_at)}${r.source_mode === "simulation" ? " · SIMULASI" : ""}${r.note ? " · " + r.note : ""}`))) : h("p", { class: "muted small-text" }, "Belum ada pengamatan pada rentang waktu ini.")));
    panel.replaceChildren(h("div", { class: "card sp-panel" }, ...body));
  }

  box.append(h("div", { class: "w-head" }, h("h2", {}, "Pos Pantau"), h("p", {}, "Pantau tinggi air tiap pos, lihat tren pada grafik, dan catat pengamatan baru.")), cards, panel);
  if (stations.length) await select(stations.find(s => s.id === current)); else panel.append(h("div", { class: "card w-empty" }, icon("pos"), h("h3", {}, "Belum ada pos pantau"), h("p", {}, "Koordinator dapat menambahkan pos pantau.")));
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
