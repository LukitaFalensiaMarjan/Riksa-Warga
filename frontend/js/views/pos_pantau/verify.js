import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { gmaps } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { badge, field, simBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { ago } from "../warga/kit.js";
import { composer } from "../umum/notifications.js";

// ---------- Pos pantau: verifikasi laporan warga dicocokkan dengan sensor sungai & cuaca ----------
const VERDICT = {
  sesuai: ["Sesuai data sensor & cuaca", "b-ok"], perlu_dicek: ["Perlu dicek di lapangan", "b-warn"],
  tidak_didukung: ["Tidak didukung data", "b-bad"], data_tidak_cukup: ["Data belum cukup", ""],
};
const TABS = [["diterima", "Menunggu"], ["terverifikasi", "Terverifikasi"], ["ditolak", "Ditolak"]];

function crossPanel(cc) {
  const [vl, vc] = VERDICT[cc.verdict] || VERDICT.data_tidak_cukup;
  return h("div", { class: "vf-cc" },
    h("div", { class: "vf-cc-h" }, h("b", {}, "Cek silang"), badge(vl, vc)),
    cc.station ? h("small", { class: "muted" }, `${cc.station.name} · ${cc.station.distance_m} m dari lokasi laporan${cc.station.level_cm != null ? ` · ${cc.station.level_cm} cm` : ""}`) : null,
    h("ul", {}, cc.signals.map(s => h("li", { class: s.ok === true ? "ok" : s.ok === false ? "no" : "na" }, h("b", {}, s.ok === true ? "✓" : s.ok === false ? "✗" : "–"), ` ${s.name}: ${s.detail}`))));
}

export async function viewVerify(box) {
  let tab = "diterima";
  const list = h("div");
  const chips = TABS.map(([k, t]) => h("button", { type: "button", class: "w-chip" + (k === tab ? " on" : ""), onclick: ev => { tab = k; chips.forEach(c => c.classList.toggle("on", c === ev.currentTarget)); load(); } }, t));

  function review(r, cc) {
    const note = h("textarea", { placeholder: "Catatan (mis. cocok dengan tinggi air di pos)", style: "min-height:80px" });
    const close = openModal(`Verifikasi laporan #${r.id}?`,
      h("p", { class: "muted small-text" }, cc ? `Cek silang: ${(VERDICT[cc.verdict] || [""])[0]}. Verifikasi ikut menentukan eskalasi peringatan.` : "Verifikasi ikut menentukan eskalasi peringatan."),
      field("Catatan", note),
      h("div", { class: "btns" }, h("button", { onclick: act(async () => {
        await api("POST", `/reports/${r.id}/verify`, { note: note.value.trim() || null });
        close(); toast("Laporan terverifikasi");
        const again = openModal("Umumkan ke semua peran?", h("p", {}, "Laporan cocok? Kirim pengumuman ke warga, koordinator, dan Tim SAR lewat aplikasi, Telegram, dan SMS."),
          h("div", { class: "btns" }, h("button", { onclick: () => { again(); composer({ title: "Banjir terverifikasi di wilayah pantauan", message: r.description, level: "waspada" }); } }, "Buat pengumuman"),
            h("button", { class: "ghost", onclick: async () => { again(); await reload(); } }, "Nanti saja")));
      }) }, "Verifikasi"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }
  function reject(r) {
    const why = h("input", { placeholder: "mis. tinggi air pos normal, tidak ada hujan" });
    const close = openModal(`Tolak laporan #${r.id}?`, field("Alasan (wajib)", why),
      h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(async () => {
        if (!why.value.trim()) throw new Error("Alasan wajib diisi");
        await api("POST", `/reports/${r.id}/reject`, { reason: why.value.trim() }); close(); await reload();
      }, "Laporan ditolak") }, "Tolak"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }

  async function load() {
    list.replaceChildren(h("p", { class: "muted" }, "Memuat…"));
    const rows = await api("GET", `/reports?status=${tab}&limit=50`);
    if (!rows.length) return list.replaceChildren(h("div", { class: "card w-empty" }, icon("check"), h("h3", {}, "Tidak ada laporan"), h("p", {}, tab === "diterima" ? "Belum ada laporan warga yang menunggu pemeriksaan." : "Belum ada laporan pada kategori ini.")));
    list.replaceChildren(...rows.map((r, i) => {
      const slot = h("div", { class: "vf-cc muted small-text" }, "Memeriksa data sensor dan cuaca…");
      let cc = null;
      api("GET", `/reports/${r.id}/crosscheck`).then(x => { cc = x; slot.replaceWith(crossPanel(x)); }).catch(() => { slot.textContent = "Cek silang gagal dimuat."; });
      return h("div", { class: "card vf rise", style: `--i:${Math.min(i, 8)}` },
        h("div", { class: "vf-h" }, h("b", {}, `Banjir #${r.id}`), simBadge(r.source_mode === "simulation"), h("span", { class: "muted small-text" }, `${ago(r.received_at)} · ${fmt(r.received_at)}`)),
        h("p", {}, r.description),
        h("div", { class: "btns" }, h("a", { href: gmaps(r.lat, r.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec small", type: "button" }, icon("pin"), "Lihat lokasi")),
          r.has_photo ? h("button", { class: "sec small", onclick: act(async ev => {
            const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
            ev.currentTarget.replaceWith(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto laporan" }));
          }) }, icon("camera"), "Foto") : null),
        slot,
        r.status === "diterima" ? h("div", { class: "btns", style: "margin-top:10px" }, h("button", { onclick: () => review(r, cc) }, "Verifikasi"), h("button", { class: "danger", onclick: () => reject(r) }, "Tolak"))
          : h("div", { class: "muted small-text", style: "margin-top:8px" }, `${r.status === "terverifikasi" ? "Terverifikasi" : "Ditolak"}${r.status_reason ? ": " + r.status_reason : ""}`));
    }));
  }

  box.append(h("div", { class: "w-head" }, h("h2", {}, "Verifikasi Laporan"), h("p", {}, "Cocokkan laporan warga dengan tinggi air sungai dan hujan, lalu verifikasi atau tolak. Laporan yang cocok bisa langsung diumumkan.")),
    h("div", { class: "w-chips" }, chips), list);
  await load();
}
