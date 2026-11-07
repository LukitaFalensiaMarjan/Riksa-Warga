import { h } from "../../lib/dom.js";
import { utc } from "../../lib/format.js";

// "5 menit lalu" — warga lebih paham waktu relatif daripada tanggal lengkap
export function ago(s) {
  if (!s) return "-";
  const m = Math.round((Date.now() - utc(s)) / 60000);
  if (m < 1) return "baru saja";
  if (m < 60) return `${m} menit lalu`;
  if (m < 1440) return `${Math.round(m / 60)} jam lalu`;
  return `${Math.round(m / 1440)} hari lalu`;
}
export const LEVEL_TEXT = {
  pantau: "Pantau — tetap tenang, tetap waspada",
  waspada: "Waspada — siapkan diri dan barang penting",
  siaga: "Siaga — bersiap pindah ke titik aman",
  evakuasi: "Evakuasi — segera menuju titik aman",
};
export const HAZ_ICON = { banjir: "banjir" };
export const HAZ_COLOR = { banjir: "#6cc4ff" };
export const LV_COLOR = { pantau: "#94a3b8", waspada: "#fbbf24", siaga: "#fb923c", evakuasi: "#ff6b6b" };

// angka naik pelan dari 0
export function countUp(el, to) {
  if (!to) { el.textContent = 0; return; }
  const t0 = performance.now();
  const f = t => { const k = Math.min(1, (t - t0) / 700); el.textContent = Math.round(to * (1 - (1 - k) ** 3)); if (k < 1) requestAnimationFrame(f); };
  requestAnimationFrame(f);
}

// ilustrasi statis (tanpa data pengguna), jadi aman disisipkan sebagai markup
export const svgBox = (cls, markup) => { const d = h("div", { class: cls, "aria-hidden": "true" }); d.innerHTML = markup; return d; };
export const SKY = '<svg viewBox="0 0 560 190" preserveAspectRatio="xMaxYMax slice"><path d="M0 190V120L70 70l60 50 50-38 70 56 60-44 80 62 70-40 100 54v20z" fill="#fff" opacity=".1"/><g fill="#fff" opacity=".2"><rect x="300" y="110" width="170" height="60"/><rect x="360" y="80" width="50" height="40"/><path d="M370 80l15-34 15 34z"/><rect x="383" y="30" width="4" height="18"/><rect x="250" y="130" width="60" height="40"/><rect x="470" y="125" width="70" height="45"/></g><g fill="#fff" opacity=".28"><circle cx="90" cy="150" r="24"/><circle cx="130" cy="156" r="18"/><circle cx="500" cy="148" r="22"/><circle cx="540" cy="158" r="16"/></g><circle cx="470" cy="40" r="22" fill="#ffd27a" opacity=".5"/></svg>';
