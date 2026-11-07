import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt, fmtDist, num } from "../../lib/format.js";
import { dist, gmaps } from "../../lib/geo.js";
import { badge, field, prioBadge } from "../../lib/ui.js";
import { openModal } from "../../lib/modal.js";
import { reload } from "../../router.js";

// ---------- Tugas Tim SAR ----------
export const FLOW = { baru: [], menunggu_penerimaan: ["diterima", "gagal"], diterima: ["menuju_lokasi", "gagal"], menuju_lokasi: ["dalam_penanganan", "gagal"], dalam_penanganan: ["selesai", "gagal"] };
export const NEXT_LABEL = { diterima: "Terima tugas", menuju_lokasi: "Berangkat ke lokasi", dalam_penanganan: "Mulai penanganan", selesai: "Selesai", gagal: "Tidak dapat dilaksanakan", dibatalkan: "Batalkan tugas" };
export const STEP_ORDER = ["menunggu_penerimaan", "diterima", "menuju_lokasi", "dalam_penanganan", "selesai"];

export function taskCard(t, { shelters = [], vols = [], isCoord = false, myPos = null } = {}) {
  const slot = h("div");
  const idx = STEP_ORDER.indexOf(t.status);
  const doStatus = (status, extra = {}) => act(async () => { await api("POST", `/tasks/${t.id}/status`, { status, ...extra }); await reload(); }, `Status: ${lab(status)}`);
  const finishForm = () => {
    const shel = h("select", {}, h("option", { value: "" }, "— tidak ke shelter —"), shelters.map(s => h("option", { value: s.id, selected: s.id === t.shelter_id }, s.name)));
    const people = h("input", { type: "number", min: 0, value: t.people_count ?? 1 });
    const note = h("textarea", { placeholder: "Apa yang dilakukan, kondisi korban, kendala (wajib)" });
    slot.replaceChildren(h("div", { class: "card flat", style: "margin:8px 0 0;background:var(--soft)" },
      h("div", { class: "row" }, field("Tiba di shelter", shel), field("Jumlah orang", people)), field("Laporan hasil tugas", note),
      h("button", { class: "green", onclick: act(async () => { await api("POST", `/tasks/${t.id}/status`, { status: "selesai", note: note.value, people_count: Number(people.value), shelter_id: num(shel.value) }); await reload(); }, "Tugas selesai") }, "Simpan selesai")));
  };
  const askReason = status => () => {
    const why = h("textarea", { placeholder: status === "gagal" ? "Mengapa tugas tidak dapat dilaksanakan?" : "Mengapa tugas dibatalkan?", style: "min-height:90px" });
    const close = openModal(status === "gagal" ? "Tugas tidak dapat dilaksanakan" : "Batalkan tugas",
      field("Alasan (wajib)", why), h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(async () => {
        if (!why.value.trim()) throw new Error("Alasan wajib diisi");
        await api("POST", `/tasks/${t.id}/status`, { status, note: why.value.trim() }); close(); await reload();
      }, "Status diperbarui") }, "Kirim"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  };
  const next = (FLOW[t.status] || []).map(s => s === "selesai" ? h("button", { class: "green", onclick: finishForm }, NEXT_LABEL[s])
    : s === "gagal" ? h("button", { class: "sec", onclick: askReason("gagal") }, NEXT_LABEL[s])
      : h("button", { class: "teal", onclick: doStatus(s) }, NEXT_LABEL[s]));
  const final = ["selesai", "gagal", "dibatalkan"].includes(t.status);
  let reassign = null;
  if (isCoord && ["baru", "menunggu_penerimaan", "diterima"].includes(t.status)) {
    const who = h("select", {}, h("option", { value: "" }, "— pilih Tim SAR —"), vols.map(u => h("option", { value: u.id, selected: u.id === t.assignee_id }, u.name)));
    reassign = h("div", { class: "row", style: "margin-top:8px" }, field(t.assignee_id ? "Tugaskan ulang ke" : "Tugaskan ke", who),
      h("button", { class: "sec", onclick: act(async () => { if (!who.value) throw new Error("Pilih Tim SAR"); await api("POST", `/tasks/${t.id}/assign`, { assignee_id: Number(who.value) }); await reload(); }, "Relawan ditugaskan") }, "Simpan"));
  }
  return h("div", { class: `card task p-${t.priority}-b` },
    h("div", { class: "btns" }, prioBadge(t.priority), badge(t.task_type.toUpperCase(), "b-info"), badge(lab(t.status), final ? (t.status === "selesai" ? "b-ok" : "b-bad") : "b-warn"),
      h("span", { class: "muted small-text" }, `#${t.id} · ${fmt(t.created_at)}${t.assignee_name ? " · " + t.assignee_name : ""}`)),
    h("div", { style: "font-size:17px;font-weight:800;margin-top:8px;color:var(--navy)" }, t.resident_name || "Tugas umum"),
    t.resident_vulnerability.length ? h("div", { class: "btns", style: "margin:4px 0" }, t.resident_vulnerability.map(v => badge(v.replaceAll("_", " "), "b-bad"))) : null,
    h("p", { style: "margin:6px 0" }, t.description),
    t.lat != null ? h("div", { class: "muted small-text" }, `Lokasi ${t.lat.toFixed(5)}, ${t.lng.toFixed(5)}${myPos ? " · ±" + fmtDist(dist(myPos, [t.lat, t.lng])) + " dari Anda" : ""} · `,
      h("a", { href: gmaps(t.lat, t.lng), target: "_blank", rel: "noopener" }, "Rute ke lokasi (Google Maps)")) : null,
    t.result ? h("div", { class: "notice " + (t.status === "selesai" ? "ok" : "bad"), style: "margin-top:8px" }, "Hasil: " + t.result) : null,
    final ? null : h("div", { class: "steps" }, STEP_ORDER.map((s, i) => h("span", { class: i < idx ? "done" : i === idx ? "now" : "" }, lab(s)))),
    final ? null : h("div", { class: "btns" }, next, isCoord ? h("button", { class: "danger", onclick: askReason("dibatalkan") }, NEXT_LABEL.dibatalkan) : null),
    reassign, slot);
}
