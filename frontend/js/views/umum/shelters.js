import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { num } from "../../lib/format.js";
import { gmaps } from "../../lib/geo.js";
import { addShelters, newMap } from "../../lib/map.js";
import { badge, field, opts, regionOptions, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Shelter ----------
export async function viewShelters(box, ctx) {
  const rows = await api("GET", "/shelters");
  const isCoord = ["koordinator"].includes(me.role);
  const canCheckin = isCoord || me.role === "tim_sar";
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
      h("select", { onchange: act(async ev => { await api("POST", `/shelters/${s.id}/status`, { status: ev.target.value }); await reload(); }, "Status shelter diubah") },
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
