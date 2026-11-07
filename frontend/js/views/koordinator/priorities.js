import { LEVEL_COLOR, PRIO_COLOR, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { fmtDist, num } from "../../lib/format.js";
import { addShelters, dotIcon, legend, newMap, pinIcon, tip } from "../../lib/map.js";
import { store } from "../../lib/store.js";
import { badge, field, lvl, opts, prioBadge, verifBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";

// ---------- Prioritas evakuasi ----------
export async function viewPriorities(box, ctx) {
  const sel = store.get("rw_prio_incident");
  const [d, users, shelters, incidents] = await Promise.all([
    api("GET", "/evacuation/priorities" + (sel ? `?incident_id=${sel}` : "")), api("GET", "/users"), api("GET", "/shelters"), api("GET", "/incidents")]);
  const vols = users.filter(u => u.role === "tim_sar" && u.is_active);
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
        }, "Tugas dibuat"),
      }, "Buat tugas"), h("button", { class: "ghost", onclick: () => slot.replaceChildren() }, "Batal"))));
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
              x.task ? null : h("button", { class: "small", onclick: () => taskForm(x, slot) }, "Tugaskan")));
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
