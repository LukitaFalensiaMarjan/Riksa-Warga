import { toast } from "./dom.js";
import { setNet } from "./offline.js";
import { logout } from "../session.js";
import { token } from "../state.js";

export async function api(method, path, body, opt = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, { method, headers, body: payload }); }
  catch { setNet(false); const e = new Error("Tidak ada koneksi ke server"); e.offline = true; throw e; }
  setNet(!r.headers.get("x-rw-offline"), r.headers.get("x-rw-time"));
  if (r.status === 401 && !opt.login) { logout(); throw new Error("Sesi berakhir, silakan login lagi"); }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const d = await r.json();
      msg = typeof d.detail === "string" ? d.detail
        : (d.detail || []).map(e => (e.loc || []).slice(1).join(".") + ": " + e.msg).join("; ");
    } catch { /* bukan JSON */ }
    throw new Error(`${r.status} — ${msg}`);
  }
  return opt.blob ? r.blob() : r.json();
}

export function act(fn, okMsg) {
  return async ev => {
    const btn = ev?.currentTarget;
    if (btn?.tagName === "BUTTON") btn.disabled = true;
    try { const r = await fn(ev); if (okMsg) toast(okMsg); return r; }
    catch (e) { if (e.message !== "batal") toast(e.message, true); }
    finally { if (btn?.tagName === "BUTTON") btn.disabled = false; }
  };
}
