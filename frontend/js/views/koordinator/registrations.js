import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { badge, table } from "../../lib/ui.js";
import { reload } from "../../router.js";

const STATUS_BADGE = { menunggu: "b-warn", disetujui: "b-ok", ditolak: "b-bad" };

// ---------- Pendaftaran warga ----------
export async function viewRegistrations(box) {
  const rows = await api("GET", "/registrations");
  const pending = rows.filter(r => r.status === "menunggu");
  const decide = (r, kind) => act(async () => {
    if (kind === "reject") {
      const reason = prompt(`Alasan menolak pendaftaran ${r.username} (wajib):`);
      if (!reason) throw new Error("batal");
      await api("POST", `/registrations/${r.id}/reject`, { reason });
    } else await api("POST", `/registrations/${r.id}/approve`);
    toast(kind === "reject" ? "Pendaftaran ditolak" : `Akun ${r.username} disetujui`);
    await reload();
  });
  box.append(h("h2", {}, "Pendaftaran Warga"),
    h("div", { class: "notice" }, "Warga yang mendaftar sendiri baru bisa masuk setelah Anda setujui. Periksa nama dan RT sebelum menyetujui; akun yang disetujui selalu berperan warga."),
    h("div", { class: "card" }, h("h3", {}, `Menunggu persetujuan (${pending.length})`), table([
      { label: "Waktu", render: r => fmt(r.created_at) }, { label: "Nama", key: "name" }, { label: "Username", key: "username" },
      { label: "RT", key: "region_name" }, { label: "Telepon", render: r => r.phone || "-" },
      { label: "Aksi", render: r => h("div", { class: "btns" },
        h("button", { class: "small", onclick: decide(r, "approve") }, "Setujui"),
        h("button", { class: "danger small", onclick: decide(r, "reject") }, "Tolak")) }], pending, "Tidak ada pendaftaran yang menunggu.")),
    h("div", { class: "card" }, h("h3", {}, "Riwayat"), table([
      { label: "Waktu", render: r => fmt(r.created_at) }, { label: "Username", key: "username" }, { label: "RT", key: "region_name" },
      { label: "Status", render: r => badge(r.status.toUpperCase(), STATUS_BADGE[r.status]) }, { label: "Alasan", render: r => r.reason || "-" }],
    rows.filter(r => r.status !== "menunggu"), "Belum ada riwayat.")));
}
