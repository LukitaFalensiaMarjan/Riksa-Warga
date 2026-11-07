import { LEVEL_COLOR } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { store } from "../../lib/store.js";
import { field, lvl, opts, simBadge, table, verifBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { reportsTable } from "./reports.js";

// ---------- Kejadian ----------
export async function viewIncidents(box) {
  const status = h("select", {}, opts(["aktif", "selesai", "dibatalkan"], store.get("rw_inc_status", "aktif")));
  status.onchange = () => { store.set("rw_inc_status", status.value); reload(); };
  const rows = await api("GET", "/incidents?status=" + status.value);
  const detail = h("div");
  const open = async id => {
    const [i, hist, alerts] = await Promise.all([api("GET", `/incidents/${id}`), api("GET", `/incidents/${id}/history`), api("GET", `/alerts?incident_id=${id}&limit=20`)]);
    const reason = h("input", { placeholder: "Alasan (wajib untuk ubah level, batal, tutup, tolak usulan)" });
    const level = h("select", {}, opts(["pantau", "waspada", "siaga", "evakuasi"], i.level));
    const live = i.status === "aktif";
    const go = (fn, ok) => act(async () => { await fn(); toast(ok); await open(id); });
    const changeLevel = go(async () => {
      if (level.value === "evakuasi" && !confirm("Evakuasi adalah keputusan pihak berwenang sesuai SOP. Lanjutkan hanya bila Anda berwenang menetapkannya.")) throw new Error("batal");
      await api("POST", `/incidents/${id}/level`, { level: level.value, reason: reason.value });
    }, "Level ditetapkan");
    detail.replaceChildren(h("div", { class: "card", style: `border-left:6px solid ${LEVEL_COLOR[i.level]}` },
      h("h3", {}, `Kejadian #${i.id} — ${i.hazard} `, lvl(i.level), " ", verifBadge(i.verification), " ", simBadge(i.is_simulation)),
      h("p", { class: "muted" }, `Status ${i.status} · ${i.unique_reporters} pelapor unik · skor ${i.score} · mulai ${fmt(i.started_at)}`),
      i.pending_level ? h("div", { class: "notice warn" }, `Usulan ${i.pending_level.toUpperCase()} menunggu sejak ${fmt(i.pending_since)}. Tanpa respons, naik otomatis dengan label BELUM DIVERIFIKASI.`) : null,
      live ? [field("Alasan / catatan", reason),
        h("div", { class: "row" }, field("Level baru", level), h("div", { class: "btns" }, h("button", { onclick: changeLevel }, "Tetapkan level"),
          h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/verify`, { note: reason.value || null }), "Kejadian diverifikasi") }, "Tandai terverifikasi"),
          i.pending_level ? h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/proposal/dismiss`, { reason: reason.value }), "Usulan ditolak") }, "Tolak usulan") : null,
          h("button", { class: "sec", onclick: go(() => api("POST", `/incidents/${id}/close`, { reason: reason.value }), "Kejadian ditutup") }, "Tutup / selesai"),
          h("button", { class: "danger", onclick: go(() => api("POST", `/incidents/${id}/cancel`, { reason: reason.value }), "Kejadian dibatalkan") }, "Batalkan")))] : null),
      h("div", { class: "card" }, h("h3", {}, "Laporan dalam kejadian"), reportsTable(i.reports, () => open(id))),
      h("div", { class: "card" }, h("h3", {}, "Riwayat perubahan"), table([
        { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Aksi", key: "action" },
        { label: "Pelaku", render: x => x.actor_id ? "user #" + x.actor_id : "sistem" },
        { label: "Perubahan", render: x => (x.old_value ? JSON.stringify(x.old_value) + " → " : "") + JSON.stringify(x.new_value || {}) },
        { label: "Alasan", render: x => x.reason || "-" }], hist)),
      h("div", { class: "card" }, h("h3", {}, "Alert kejadian ini"), table([
        { label: "#", key: "id" }, { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Jenis", key: "kind" },
        { label: "Internal", render: x => x.internal ? "Ya" : "Tidak" }, { label: "Pesan", render: x => h("pre", { class: "msg" }, x.message) }], alerts)));
    detail.scrollIntoView({ behavior: "smooth" });
  };
  box.append(h("h2", {}, "Kejadian"), h("div", { class: "row", style: "max-width:300px" }, field("Status", status)),
    h("div", { class: "card" }, table([
      { label: "#", key: "id" }, { label: "Jenis", render: i => [i.hazard, " ", simBadge(i.is_simulation)] },
      { label: "Level", render: i => lvl(i.level) }, { label: "Verifikasi", render: i => verifBadge(i.verification) },
      { label: "Pelapor unik", key: "unique_reporters" }, { label: "Terakhir", render: i => fmt(i.last_report_at) },
      { label: "", render: i => h("button", { class: "small", onclick: act(() => open(i.id)) }, "Buka") },
    ], rows, "Tidak ada kejadian.")), detail);
  const want = store.get("rw_open");
  if (want) { store.del("rw_open"); await open(Number(want)); }
}
