import { api } from "./api.js";
import { dist } from "./geo.js";
import { me } from "../state.js";

// Lokasi siaga: setelah warga memberi izin sekali, posisi dikirim berkala selama aplikasi terbuka.
// Peramban tidak mengizinkan pelacakan saat aplikasi ditutup; di luar itu yang tersimpan adalah posisi terakhir.
const EVERY_MS = 120000, MOVED_M = 100, MIN_GAP_MS = 15000;
let watchId = null, lastAt = 0, lastPos = null;

export const isTracking = () => watchId != null;

export function stopTracking() {
  if (watchId != null) navigator.geolocation?.clearWatch(watchId);
  watchId = null; lastAt = 0; lastPos = null;
}

export function startTracking() {
  stopTracking();
  if (!navigator.geolocation) return;
  watchId = navigator.geolocation.watchPosition(async p => {
    const pos = [p.coords.latitude, p.coords.longitude], now = Date.now();
    const moved = lastPos ? dist(lastPos, pos) : Infinity;
    if (now - lastAt < MIN_GAP_MS || (now - lastAt < EVERY_MS && moved < MOVED_M)) return;
    lastAt = now; lastPos = pos;
    try { await api("POST", "/me/location", { lat: pos[0], lng: pos[1], kind: "auto" }); }
    catch (e) { if (String(e.message).startsWith("403")) stopTracking(); }  // izin dicabut dari perangkat lain
  }, () => { /* GPS belum tersedia: coba lagi otomatis */ }, { enableHighAccuracy: true, maximumAge: 30000, timeout: 20000 });
}

// dipanggil sekali setelah masuk: bila sudah pernah memberi izin, pelacakan menyala lagi tanpa bertanya
export async function initTracking() {
  if (me?.role !== "warga") return;
  try { if ((await api("GET", "/me/resident")).consent) startTracking(); } catch { /* offline */ }
}
