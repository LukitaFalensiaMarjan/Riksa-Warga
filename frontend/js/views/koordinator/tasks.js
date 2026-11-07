import { PRIO_COLOR, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { num } from "../../lib/format.js";
import { addShelters, newMap, pinIcon, tip } from "../../lib/map.js";
import { store } from "../../lib/store.js";
import { field, opts, regionOptions } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { taskCard } from "../umum/taskCard.js";

export async function viewTasks(box, ctx) {
  const [tasks, users, shelters, regions] = await Promise.all([api("GET", "/tasks"), api("GET", "/users"), api("GET", "/shelters"), api("GET", "/regions")]);
  const vols = users.filter(u => u.role === "tim_sar" && u.is_active);
  const usable = shelters.filter(s => s.is_verified);
  const showAll = store.get("rw_tasks_all", false);
  const list = tasks.filter(t => showAll || !["selesai", "gagal", "dibatalkan"].includes(t.status));
  const f = { type: h("select", {}, opts(["evakuasi", "medis", "logistik", "damkar", "sar", "lainnya"])), prio: h("select", {}, opts(["kritis", "tinggi", "sedang", "rendah"], "sedang")),
    region: h("select", {}, regionOptions(regions, me.region_id)), desc: h("textarea", { placeholder: "Instruksi tugas" }),
    who: h("select", {}, h("option", { value: "" }, "— belum ditugaskan —"), vols.map(u => h("option", { value: u.id }, u.name))),
    shel: h("select", {}, h("option", { value: "" }, "— tanpa shelter —"), usable.map(s => h("option", { value: s.id }, s.name))),
    lat: h("input", { type: "number", step: "any" }), lng: h("input", { type: "number", step: "any" }) };
  box.append(h("h2", {}, "Permintaan Bantuan SAR"),
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
