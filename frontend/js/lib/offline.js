import { act, api } from "./api.js";
import { h, toast } from "./dom.js";
import { fmt, uid } from "./format.js";
import { store } from "./store.js";
import { me, netbar, token } from "../state.js";

export const QKEY = "rw_queue";
export function enqueue(path, body, label) {
  const q = store.get(QKEY, []);
  q.push({ id: uid(), path, body, label, at: new Date().toISOString(), user: me?.id });
  store.set(QKEY, q); setNet(navigator.onLine);
}
export async function flushQueue() {
  const q = store.get(QKEY, []);
  if (!q.length || !token || !me) return;
  const rest = [];
  for (const item of q) {
    if (item.user !== me.id) { rest.push(item); continue; }
    try { await api("POST", item.path, item.body); toast("Terkirim dari antrean: " + item.label); }
    catch (e) { if (e.offline) rest.push(item); else toast(`Antrean "${item.label}" ditolak: ${e.message}`, true); }
  }
  store.set(QKEY, rest); setNet(navigator.onLine);
}
// kirim; bila tidak ada koneksi simpan ke antrean perangkat
export async function postOrQueue(path, body, label) {
  try { return { sent: true, data: await api("POST", path, body) }; }
  catch (e) {
    if (!e.offline) throw e;
    enqueue(path, body, label);
    toast("Tidak ada koneksi — disimpan di perangkat, dikirim otomatis saat online");
    return { sent: false };
  }
}

// ---------- status jaringan ----------
export let netState = { online: true, at: null };
export function setNet(online, at) {
  netState = { online, at: online ? null : at || netState.at };
  if (!netbar) return;
  const q = store.get(QKEY, []).filter(i => i.user === me?.id).length;
  if (online && !q) { netbar.hidden = true; return; }
  netbar.hidden = false;
  netbar.className = "netbar" + (online ? "" : " offline");
  // h() meratakan & membuang null; replaceChildren native akan menulis "null"
  netbar.replaceChildren(h("span", {}, online ? `${q} kiriman menunggu di antrean perangkat.`
    : `Offline — menampilkan data tersimpan${netState.at ? " (" + fmt(netState.at) + ")" : ""}. ${q ? q + " kiriman menunggu." : ""}`,
  online && q ? h("button", { class: "small", onclick: act(flushQueue) }, "Kirim sekarang") : null));
}
window.addEventListener("online", () => { setNet(true); flushQueue(); });
window.addEventListener("offline", () => setNet(false));
