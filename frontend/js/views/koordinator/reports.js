import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { store } from "../../lib/store.js";
import { badge, field, opts, simBadge, table } from "../../lib/ui.js";
import { reload } from "../../router.js";

// ---------- Laporan (koordinator) ----------
export function reportsTable(rows, after) {
  const review = (r, kind) => act(async () => {
    if (kind === "reject") {
      const reason = prompt("Alasan menolak laporan #" + r.id + " (wajib):");
      if (!reason) throw new Error("batal");
      await api("POST", `/reports/${r.id}/reject`, { reason });
    } else await api("POST", `/reports/${r.id}/verify`, { note: prompt("Catatan verifikasi (opsional, mis. metode):") || null });
    toast("Laporan diperbarui"); await after();
  });
  const photo = async (r, cell) => {
    const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
    cell.replaceChildren(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto" }));
  };
  return table([
    { label: "#", key: "id" },
    { label: "Laporan", render: r => [h("b", {}, r.hazard), " ", simBadge(r.source_mode === "simulation"), h("div", {}, r.description), h("div", { class: "muted small-text" }, `${r.lat.toFixed(5)}, ${r.lng.toFixed(5)} · pelapor #${r.reporter_id} · ${lab(r.source)} · ${fmt(r.received_at)}`)] },
    { label: "Status", render: r => [badge(lab(r.status), r.status === "terverifikasi" ? "b-ok" : r.status === "ditolak" ? "b-bad" : "b-info"), r.duplicate_of ? h("div", { class: "muted small-text" }, "duplikat #" + r.duplicate_of) : null, r.status_reason ? h("div", { class: "muted small-text" }, r.status_reason) : null] },
    { label: "Skor", render: r => [h("b", {}, r.score), r.flags.length ? h("div", {}, r.flags.map(f => badge(f.replaceAll("_", " "), "b-bad"))) : null,
      h("details", {}, h("summary", {}, "faktor"), r.score_factors.map(f => h("div", { class: "factor" }, `${f.poin >= 0 ? "+" : ""}${f.poin} ${f.faktor}: ${f.keterangan}`)))] },
    { label: "Foto", render: r => { const c = h("span"); if (r.has_photo) c.append(h("button", { class: "sec small", onclick: act(() => photo(r, c)) }, "Lihat")); else c.append("-"); return c; } },
    { label: "Aksi", render: r => ["diterima", "duplikat"].includes(r.status) ? h("div", { class: "btns" },
      r.status === "diterima" ? h("button", { class: "small", onclick: review(r, "verify") }, "Verifikasi") : null,
      h("button", { class: "danger small", onclick: review(r, "reject") }, "Tolak")) : "-" },
  ], rows, "Tidak ada laporan.");
}

export async function viewReports(box) {
  const st = h("select", {}, opts([["", "Semua status"], ["diterima", "Diterima"], ["terverifikasi", "Terverifikasi"], ["ditolak", "Ditolak"], ["duplikat", "Duplikat"]], store.get("rw_rep_status", "")));
  st.onchange = () => { store.set("rw_rep_status", st.value); reload(); };
  const rows = await api("GET", "/reports?limit=200" + (st.value ? "&status=" + st.value : ""));
  box.append(h("h2", {}, "Laporan Masuk"), h("div", { class: "notice" }, "Skor hanya alat bantu prioritas, bukan bukti. Laporan berskor rendah tetap disimpan dan bisa diperiksa."),
    h("div", { class: "row", style: "max-width:300px" }, field("Filter", st)), h("div", { class: "card" }, reportsTable(rows, reload)));
}
