import { lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { QKEY, flushQueue } from "../../lib/offline.js";
import { store } from "../../lib/store.js";
import { badge, simBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { HAZ_COLOR, HAZ_ICON, ago, countUp } from "./kit.js";

// ---------- Laporan saya (warga): kartu dengan pelacak status ----------
const STATE = {
  diterima: { c: "#6cc4ff", step: 2, text: "Laporan Anda sudah masuk. Koordinator sedang memeriksa." },
  terverifikasi: { c: "#5fe0c0", step: 3, text: "Terbukti benar dan dipakai untuk peringatan warga. Terima kasih!" },
  ditolak: { c: "#ff8a7d", step: 3, text: "Laporan tidak dapat dipakai. Lihat alasan di bawah." },
  duplikat: { c: "#ffd98a", step: 3, text: "Sudah ada laporan sama dari warga lain — digabung ke kejadian yang sama." },
};

export async function viewWargaMine(box) {
  const rows = await api("GET", "/reports/mine");
  const queued = store.get(QKEY, []).filter(i => i.user === me.id);
  const n = k => rows.filter(r => r.status === k).length;
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Laporan Saya"), h("p", {}, "Pantau apa yang terjadi pada laporan yang Anda kirim.")));
  if (rows.length) box.append(h("div", { class: "rp-stats" },
    h("div", {}, h("b", { "data-n": rows.length }, 0), h("span", {}, "Dikirim")), h("div", {}, h("b", { "data-n": n("terverifikasi") }, 0), h("span", {}, "Terverifikasi")),
    h("div", {}, h("b", { "data-n": n("diterima") }, 0), h("span", {}, "Diperiksa"))));
  setTimeout(() => box.querySelectorAll("[data-n]").forEach(b => countUp(b, +b.dataset.n)), 50);
  if (queued.length) box.append(h("div", { class: "card notice warn", style: "padding:14px" },
    h("b", {}, `${queued.length} laporan menunggu sinyal`), h("div", { class: "small-text" }, queued.map(q => `${q.label} (${ago(q.at)})`).join(", ")),
    h("button", { class: "small", style: "margin-top:8px", onclick: act(async () => { await flushQueue(); await reload(); }) }, "Kirim sekarang")));
  if (!rows.length) { box.append(h("div", { class: "card w-empty" }, icon("lapor"), h("h3", {}, "Belum ada laporan"), h("p", {}, "Lihat air naik atau banjir? Laporan Anda membantu tetangga."), h("button", { onclick: () => { location.hash = "#lapor"; } }, "Lapor kejadian"))); return; }

  rows.forEach((r, i) => {
    const st = STATE[r.status] || STATE.diterima, hc = HAZ_COLOR[r.hazard] || "#9fc9c1";
    const last = r.status === "ditolak" ? "Ditolak" : r.status === "duplikat" ? "Digabung" : "Terverifikasi";
    const photoSlot = h("div");
    box.append(h("div", { class: "card rp rise", style: `--rc:${st.c};--i:${Math.min(i, 8)}` },
      h("div", { class: "rp-top" },
        h("div", { class: "rp-ico", style: `--rc:${hc}` }, icon(HAZ_ICON[r.hazard] || "kejadian")),
        h("div", { class: "grow" }, h("h4", {}, r.hazard[0].toUpperCase() + r.hazard.slice(1) + ` · #${r.id}`),
          h("div", { class: "muted small-text" }, `${ago(r.received_at)} · ${fmt(r.received_at)}`)),
        simBadge(r.source_mode === "simulation")),
      h("p", { class: "rp-desc" }, r.description),
      h("div", { class: "track" }, ["Terkirim", "Diperiksa", last].map((t, k) => h("div", { class: k < st.step ? "on" : "" }, t))),
      h("div", { class: "small-text", style: `color:${st.c};font-weight:700` }, st.text),
      r.status_reason ? h("div", { class: "rp-note", style: "margin-top:10px" }, h("b", {}, "Catatan koordinator"), r.status_reason) : null,
      h("div", { class: "btns", style: "margin-top:12px;align-items:center" },
        r.incident_id ? badge("Kejadian #" + r.incident_id, "b-info") : badge("Belum masuk kejadian"),
        r.has_photo ? h("button", { class: "sec small", onclick: act(async ev => {
          const blob = await api("GET", `/reports/${r.id}/photo`, undefined, { blob: true });
          photoSlot.replaceChildren(h("img", { class: "photo", src: URL.createObjectURL(blob), alt: "Foto laporan" })); ev.currentTarget.hidden = true;
        }) }, icon("camera"), " Lihat foto") : null),
      photoSlot));
  });
}
