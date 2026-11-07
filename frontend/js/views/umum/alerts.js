import { LEVEL_COLOR } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { badge, lvl, table, verifBadge } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Peringatan ----------
export async function viewAlerts(box) {
  const rows = await api("GET", "/alerts?limit=50");
  const isCoord = ["koordinator"].includes(me.role);
  box.append(h("h2", {}, "Peringatan"), h("div", { class: "btns no-print", style: "margin-bottom:12px" }, h("button", { class: "sec small", onclick: reload }, "Segarkan")));
  if (!rows.length) box.append(h("div", { class: "notice ok" }, "Belum ada peringatan untuk wilayah Anda."));
  for (const a of rows) {
    const dl = h("div");
    box.append(h("div", { class: "card", style: `border-left:6px solid ${LEVEL_COLOR[a.level] || "#cbd5e1"}` },
      h("div", { class: "btns" }, badge(a.kind.toUpperCase()), a.level ? lvl(a.level) : null,
        a.verification ? verifBadge(a.verification) : null, a.internal ? badge("INTERNAL", "b-warn") : null,
        h("span", { class: "muted small-text" }, `#${a.id}${a.incident_id ? ` · kejadian #${a.incident_id}` : ""} · ${fmt(a.created_at)}`)),
      h("pre", { class: "msg" }, a.message),
      isCoord ? h("button", {
        class: "sec small",
        onclick: act(async () => {
          const d = await api("GET", `/alerts/${a.id}/deliveries`);
          dl.replaceChildren(table([
            { label: "Kanal", key: "channel" }, { label: "Penerima (chat ID)", key: "recipient" },
            { label: "Status", render: x => badge(x.status.toUpperCase(), x.status === "gagal" ? "b-bad" : "b-ok") },
            { label: "Galat", render: x => x.error || "-" }, { label: "Waktu", render: x => fmt(x.created_at) },
          ], d, "Belum ada pengiriman Telegram: tidak ada penerima dengan chat ID."));
        }),
      }, "Status pengiriman Telegram") : null, dl));
  }
}
