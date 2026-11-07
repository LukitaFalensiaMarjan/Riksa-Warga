import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { QKEY, flushQueue } from "../../lib/offline.js";
import { store } from "../../lib/store.js";
import { badge, simBadge, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Laporan saya ----------
export async function viewMine(box) {
  const rows = await api("GET", "/reports/mine");
  const queued = store.get(QKEY, []).filter(i => i.user === me.id);
  const showPhoto = async (r, cell) => {
    const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
    cell.replaceChildren(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto laporan" }));
  };
  box.append(h("h2", {}, "Laporan Saya"));
  if (queued.length) box.append(h("div", { class: "card" }, h("h3", {}, "Menunggu dikirim (tersimpan di perangkat)"),
    table([{ label: "Jenis", key: "label" }, { label: "Disimpan", render: q => fmt(q.at) }], queued),
    h("button", { class: "small", onclick: act(async () => { await flushQueue(); await reload(); }) }, "Kirim sekarang")));
  box.append(h("div", { class: "card" }, table([
    { label: "#", key: "id" },
    { label: "Jenis", render: r => [h("b", {}, r.hazard), " ", simBadge(r.source_mode === "simulation")] },
    { label: "Status", render: r => badge(lab(r.status), r.status === "terverifikasi" ? "b-ok" : r.status === "ditolak" ? "b-bad" : "b-info") },
    { label: "Catatan koordinator", render: r => r.status_reason || "-" },
    { label: "Kejadian", render: r => r.incident_id ? "#" + r.incident_id : "-" },
    { label: "Dikirim", render: r => fmt(r.received_at) },
    { label: "Foto", render: r => { const c = h("span"); if (r.has_photo) c.append(h("button", { class: "sec small", onclick: act(() => showPhoto(r, c)) }, "Lihat")); else c.append("-"); return c; } },
  ], rows, "Anda belum mengirim laporan.")));
}
