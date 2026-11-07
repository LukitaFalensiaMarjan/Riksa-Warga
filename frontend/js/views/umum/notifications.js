import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { paintBadge } from "../../lib/notifwatch.js";
import { field, opts } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { ago } from "../warga/kit.js";

// ---------- Notifikasi: pengumuman, peringatan prediksi banjir, shelter penuh ----------
const KIND = { pengumuman: ["inbox", "Pengumuman"], prediksi: ["cuaca", "Prediksi banjir"], shelter: ["shelter", "Shelter"] };
const LEVEL_C = { info: "#1e88f0", waspada: "#d97706", bahaya: "#dc2626" };

export function composer(pre = {}) {
  const title = h("input", { placeholder: "mis. Sungai Hulu meluap", maxlength: 120, value: pre.title || "" });
  const msg = h("textarea", { placeholder: "Apa yang harus warga dan petugas lakukan?", style: "min-height:110px" });
  msg.value = pre.message || "";
  const level = h("select", {}, opts([["info", "Informasi"], ["waspada", "Waspada"], ["bahaya", "Bahaya"]], pre.level || "waspada"));
  const scope = h("select", {}, opts([["wilayah", "Kelurahan saya"], ["semua", "Seluruh kota"]]));
  const close = openModal("Buat pengumuman",
    h("p", { class: "muted small-text" }, "Dikirim ke warga, koordinator, Tim SAR, dan pos pantau (bukan admin) lewat aplikasi, Telegram, dan SMS."),
    field("Judul", title), field("Isi pengumuman", msg), h("div", { class: "row" }, field("Tingkat", level), field("Sasaran", scope)),
    h("div", { class: "btns" }, h("button", {
      onclick: act(async () => {
        const r = await api("POST", "/announcements", { title: title.value, message: msg.value, level: level.value, scope: scope.value });
        close(); toast(`Terkirim ke ${r.recipients} orang (Telegram ${r.telegram}, SMS ${r.sms})`); await reload();
      }),
    }, "Kirim pengumuman"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
}

export async function viewNotifications(box) {
  const rows = await api("GET", "/notifications");
  let only = false;
  const list = h("div");
  const unread = () => rows.filter(n => !n.read_at).length;
  const chips = [["Semua", false], ["Belum dibaca", true]].map(([t, v]) => h("button", { type: "button", class: "w-chip" + (v === only ? " on" : ""), onclick: ev => { only = v; chips.forEach(c => c.classList.toggle("on", c === ev.currentTarget)); draw(); } }, t));
  const canPost = ["pos_pantau", "koordinator"].includes(me.role);

  async function open(n, el) {
    if (!n.read_at) { await api("POST", `/notifications/${n.id}/read`); n.read_at = new Date().toISOString(); el.classList.remove("unread"); paintBadge(unread()); }
  }
  function draw() {
    const shown = rows.filter(n => !only || !n.read_at);
    list.replaceChildren(...(shown.length ? shown.map((n, i) => {
      const [ic, kl] = KIND[n.kind] || KIND.pengumuman;
      const el = h("div", { class: "card nf rise" + (n.read_at ? "" : " unread"), style: `--lc:${LEVEL_C[n.level] || LEVEL_C.info};--i:${Math.min(i, 8)}`, onclick: () => open(n, el) },
        h("span", { class: "nf-ico" }, icon(ic)),
        h("div", { class: "nf-t" }, h("div", { class: "nf-h" }, h("b", {}, n.title), h("span", { class: "badge" }, kl)), h("p", {}, n.body),
          h("small", { class: "muted" }, ago(n.created_at)), n.link ? h("a", { class: "d-link", href: "#" + n.link, onclick: () => open(n, el) }, "Buka", icon("arrow")) : null));
      return el;
    }) : [h("div", { class: "card w-empty" }, icon("inbox"), h("h3", {}, only ? "Semua sudah dibaca" : "Belum ada notifikasi"), h("p", {}, "Pengumuman pos pantau, peringatan potensi banjir, dan info shelter penuh akan muncul di sini."))]));
  }
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Notifikasi"), h("p", {}, "Pengumuman dan peringatan untuk wilayah Anda. Yang penting juga dikirim ke Telegram dan SMS.")),
    h("div", { class: "w-chips" }, chips,
      unread() ? h("button", { class: "w-chip", type: "button", onclick: act(async () => { await api("POST", "/notifications/read-all"); paintBadge(0); await reload(); }) }, "Tandai semua dibaca") : null,
      canPost ? h("button", { type: "button", class: "n-announce", onclick: composer }, icon("alert"), "Buat pengumuman") : null), list);
  draw();
  paintBadge(unread());
}
