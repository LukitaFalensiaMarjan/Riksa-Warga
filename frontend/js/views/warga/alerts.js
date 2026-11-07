import { LEVEL_RANK } from "../../config.js";
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { badge, verifBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { LEVEL_TEXT, LV_COLOR, ago } from "./kit.js";
import { actionLine, activeAlerts } from "./home.js";

// ---------- Peringatan (warga) ----------
export async function viewWargaAlerts(box) {
  const rows = await api("GET", "/alerts?limit=50");
  const live = new Set(activeAlerts(rows).map(a => a.id));
  let filter = "semua";
  const list = h("div");
  const levels = ["semua", "aktif", ...Object.keys(LEVEL_RANK).reverse()];
  const countOf = f => f === "semua" ? rows.length : f === "aktif" ? live.size : rows.filter(a => a.level === f).length;
  const chips = levels.map(f => h("button", { type: "button", class: "w-chip" + (f === filter ? " on" : ""), onclick: () => { filter = f; chips.forEach((c, i) => c.classList.toggle("on", levels[i] === f)); draw(); } },
    f === "semua" ? "Semua" : f === "aktif" ? "Sedang berlaku" : f[0].toUpperCase() + f.slice(1), h("i", {}, countOf(f))));

  function draw() {
    const shown = rows.filter(a => filter === "semua" || (filter === "aktif" ? live.has(a.id) : a.level === filter));
    list.replaceChildren(...(shown.length ? shown.map((a, i) => card(a, i)) : [h("div", { class: "card w-empty" }, icon("alert"), h("h3", {}, "Tidak ada peringatan"), h("p", {}, "Tidak ada peringatan pada kategori ini."))]));
  }
  function card(a, i) {
    const lv = a.level, sim = a.message.startsWith("[SIMULASI]"), todo = actionLine(a.message) || (lv && LEVEL_TEXT[lv]);
    return h("div", { class: "card al rise", style: `--lc:${LV_COLOR[lv] || "#9fc9c1"};--i:${Math.min(i, 8)}` },
      h("div", { class: "al-ico" }, icon(lv === "evakuasi" || lv === "siaga" ? "kejadian" : "alert")),
      h("div", {},
        h("div", { class: "btns", style: "align-items:center" },
          h("h4", {}, lv ? `${lv.toUpperCase()}${a.incident_id ? " · kejadian #" + a.incident_id : ""}` : a.kind.toUpperCase()),
          live.has(a.id) ? h("span", { class: "al-live" }, "BERLAKU") : null),
        h("div", { class: "al-meta" }, `${ago(a.created_at)} · ${fmt(a.created_at)}`),
        h("div", { class: "btns", style: "margin-top:6px" }, a.verification ? verifBadge(a.verification) : null, sim ? badge("SIMULASI", "b-sim") : null),
        todo ? h("div", { class: "al-do" }, h("b", {}, "Yang harus dilakukan"), todo) : null,
        h("details", {}, h("summary", {}, "Pesan lengkap"), h("pre", { class: "msg" }, a.message))));
  }
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Peringatan"), h("p", {}, "Pesan resmi untuk wilayah Anda. Yang terbaru ada di atas.")),
    h("div", { class: "w-chips" }, chips, h("button", { class: "w-chip", type: "button", onclick: reload }, "Segarkan")), list);
  draw();
}
