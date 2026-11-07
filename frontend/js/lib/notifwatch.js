import { api } from "./api.js";
import { h, toast } from "./dom.js";
import { me, token } from "../state.js";

// Lencana jumlah notifikasi belum dibaca di menu; diperiksa tiap 45 detik, toast bila ada yang baru.
let timer = null, last = null;

export function paintBadge(n) {
  document.querySelectorAll('[data-id="notif"]').forEach(a => {
    a.querySelector(".nbadge")?.remove();
    if (n > 0) a.append(h("em", { class: "nbadge", "aria-label": `${n} belum dibaca` }, n > 99 ? "99+" : n));
  });
  last = n;
}

export function watchNotifications() {
  clearInterval(timer); last = null;
  if (!me || me.role === "admin") return;
  const tick = async () => {
    if (!token) return clearInterval(timer);
    try {
      const { unread } = await api("GET", "/notifications/unread-count");
      if (last != null && unread > last) toast("Ada notifikasi baru — buka menu Notifikasi");
      paintBadge(unread);
    } catch { /* offline: coba lagi pada putaran berikutnya */ }
  };
  tick();
  timer = setInterval(tick, 45000);
}
