import { act, api } from "../../lib/api.js";
import { $, app, h } from "../../lib/dom.js";
import { getPosition } from "../../lib/geo.js";
import { avatar } from "../../lib/avatar.js";
import { watchNotifications } from "../../lib/notifwatch.js";
import { initTracking } from "../../lib/tracker.js";
import { applyTheme, themeBtn } from "../../lib/theme.js";
import { icon } from "../../lib/icons.js";
import { setNet } from "../../lib/offline.js";
import { field } from "../../lib/ui.js";
import { show } from "../../router.js";
import { logout } from "../../session.js";
import { main, me, netbar, setMain, setMe, setNetbar } from "../../state.js";
import { ROLE_LABEL, TABS, tabsFor } from "../../tabs.js";

// peran yang memakai tema bergaya halaman masuk (warga dan admin)
const WARGA_UI = ["warga", "admin", "koordinator", "pos_pantau", "tim_sar"];

export function renderShell() {
  const tabs = tabsFor(me.role);
  document.body.classList.toggle("tw", WARGA_UI.includes(me.role));
  applyTheme();
  const tb = WARGA_UI.includes(me.role) ? themeBtn : () => null;
  const link = id => h("a", { href: "#" + id, "data-id": id }, icon(TABS[id].icon), h("span", {}, TABS[id].label));
  const openProfile = () => profile();
  setNetbar(h("div", { class: "netbar", hidden: true }));
  setMain(h("main"));
  const bubs = WARGA_UI.includes(me.role) ? h("div", { class: "bubs" }, [[8, 14, 90], [88, 10, 60], [78, 80, 120], [4, 76, 70], [50, 92, 50]].map(([x, y, z], i) => h("i", { class: "bub", style: `left:${x}%;top:${y}%;width:${z}px;height:${z}px;animation-delay:${-i * 2.3}s` }))) : null;
  app.replaceChildren(h("div", { class: "shell" }, bubs,
    h("aside", { class: "side" },
      h("div", { class: "brand" }, h("img", { src: "/icons/logo-64.png", alt: "" }), h("div", {}, h("b", {}, "Riksa Warga"), h("span", {}, "Saling jaga, saling kabari"))),
      h("nav", { class: "nav" }, tabs.map(link)),
      h("div", { class: "me" }, avatar(), h("div", { class: "me-id" }, h("b", {}, me.name), h("span", {}, ROLE_LABEL[me.role] || me.role)),
        h("div", { class: "row2" }, tb(), h("button", { onclick: openProfile }, "Profil"), h("button", { onclick: logout }, "Keluar")))),
    h("div", { class: "content" },
      h("div", { class: "topbar" }, h("img", { src: "/icons/logo-64.png", alt: "" }), h("b", {}, "Riksa Warga"),
        avatar("sm"), tb(), h("button", { onclick: openProfile }, "Profil"), h("button", { onclick: logout }, "Keluar")),
      h("nav", { class: "mnav" }, tabs.map(link)),
      netbar, main)));
  setNet(navigator.onLine);
  const route = () => {
    const id = tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : tabs[0];
    document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.id === id));
    show(id);
  };
  window.onhashchange = route;
  route();
  watchNotifications();
  initTracking();
}

// Profil sebagai popup di atas halaman: Esc, klik latar, atau tombol Tutup menutupnya.
export function profile() {
  if ($(".modal-bg")) return;
  const tg = h("input", { value: me.telegram_chat_id || "", placeholder: "mis. 1949754174", inputmode: "numeric" });
  const ph = h("input", { value: me.phone || "" });
  const prev = document.activeElement;
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const bg = h("div", { class: "modal-bg no-print", onclick: e => { if (e.target === bg) close(); } },
    h("div", { class: "card modal", role: "dialog", "aria-modal": "true", "aria-label": "Profil dan kanal kontak" },
      h("div", { class: "modal-h" }, h("h3", {}, "Profil & kanal kontak"), h("button", { class: "ghost modal-x", "aria-label": "Tutup", onclick: close }, "✕")),
      h("p", { class: "muted small-text" }, "Telegram chat ID agar akun ini menerima peringatan. Kirim /start ke bot Riksa Warga lebih dulu."),
      field("Telegram chat ID", tg), field("Telepon", ph),
      h("div", { class: "btns" },
        h("button", { onclick: act(async () => { setMe(await api("PATCH", "/auth/me", { telegram_chat_id: tg.value.trim(), phone: ph.value.trim() })); close(); }, "Profil tersimpan") }, "Simpan"),
        h("button", { class: "sec", onclick: act(async () => { const p = await getPosition(); await api("POST", "/me/location", { lat: p[0], lng: p[1], kind: "rumah" }); }, "Lokasi rumah disimpan dari GPS") }, "Simpan lokasi rumah (GPS)"),
        h("button", { class: "ghost", onclick: close }, "Tutup"))));
  document.addEventListener("keydown", onKey);
  document.body.append(bg);
  tg.focus();
}
