import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h, toast } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { ROUTE_STYLE, addHazards, addRoutes, addShelters, legend, newMap } from "../../lib/map.js";
import { field, opts, regionOptions, simBadge, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Peta & rute (koordinator) ----------
export async function viewRouteAdmin(box, ctx) {
  const [routes, hazards, shelters, regions] = await Promise.all([api("GET", "/evacuation-routes"), api("GET", "/road-conditions"), api("GET", "/shelters"), api("GET", "/regions")]);
  let mode = "lihat", draft = [], draftLine = null, map = null;
  const region = h("select", {}, regionOptions(regions, me.region_id));
  const kind = h("select", {}, opts(["jalan_tertutup", "genangan", "pohon_tumbang", "kabel_listrik", "lainnya"]));
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
