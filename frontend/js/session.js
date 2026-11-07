import { stopTracking } from "./lib/tracker.js";
import { api } from "./lib/api.js";
import { toast } from "./lib/dom.js";
import { stopMaps } from "./lib/map.js";
import { flushQueue } from "./lib/offline.js";
import { store } from "./lib/store.js";
import { stopTimer } from "./router.js";
import { cfg, setCfg, setMe, setNetbar, setToken, token } from "./state.js";
import { renderLogin } from "./views/umum/login.js";
import { renderShell } from "./views/umum/shell.js";

export function logout() {
  setToken(null); setMe(null);
  store.del("rw_token");
  navigator.serviceWorker?.controller?.postMessage("logout");
  document.body.classList.remove("tw");
  stopTimer(); stopMaps(); setNetbar(null); stopTracking();
  renderLogin();
}

export function registerSW() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { /* butuh localhost/HTTPS */ });
}

export async function boot() {
  registerSW();
  try { setCfg({ ...cfg, ...(await api("GET", "/config")) }); } catch { /* pakai default */ }
  if (!token) return renderLogin();
  try { setMe(await api("GET", "/auth/me")); } catch (e) { toast(e.message, true); return renderLogin(); }
  renderShell();
  flushQueue();
}
