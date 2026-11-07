import { lab } from "../config.js";
import { h } from "./dom.js";

export const field = (label, input) => h("label", { class: "f" }, label, input);
export const opts = (list, sel) => list.map(v => Array.isArray(v)
  ? h("option", { value: v[0], selected: String(v[0]) === String(sel) }, v[1])
  : h("option", { value: v, selected: v === sel }, lab(v)));
export const badge = (text, cls = "") => h("span", { class: "badge " + cls }, text);
export const lvl = l => badge(l.toUpperCase(), "b-" + l);
export const verifBadge = v => badge(lab(v), v === "terverifikasi" ? "b-ok" : "b-warn");
export const simBadge = on => on ? badge("SIMULASI", "b-sim") : null;
export const prioBadge = p => badge(p.toUpperCase(), "p-" + p);

export function table(cols, rows, empty = "Belum ada data.") {
  cols = cols.filter(Boolean);
  if (!rows.length) return h("p", { class: "muted" }, empty);
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, cols.map(c => h("th", {}, c.label)))),
    h("tbody", {}, rows.map(r => h("tr", {}, cols.map(c => h("td", {}, c.render ? c.render(r) : r[c.key])))))));
}

export const REGION_ORDER = { kelurahan: 0, rw: 1, rt: 2, kecamatan: 3, kabupaten_kota: 4, provinsi: 5 };
export function regionOptions(regions, sel, levels) {
  return regions.filter(r => !levels || levels.includes(r.level))
    .sort((a, b) => REGION_ORDER[a.level] - REGION_ORDER[b.level] || a.id - b.id)
    .map(r => h("option", { value: r.id, selected: r.id === sel }, `${r.name} (${r.level.toUpperCase()})`));
}
