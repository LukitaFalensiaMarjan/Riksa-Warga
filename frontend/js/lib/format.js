
export const utc = s => new Date(/(Z|[+-]\d\d:\d\d)$/.test(s) ? s : s + "Z");  // API: UTC tanpa zona
export const fmt = s => s ? utc(s).toLocaleString("id-ID", { timeZone: "Asia/Jakarta", dateStyle: "short", timeStyle: "short" }) + " WIB" : "-";
export const fmtDist = m => m == null ? "-" : m >= 1000 ? (m / 1000).toFixed(1) + " km" : Math.round(m) + " m";
export const fmtDur = s => s == null ? "-" : s < 60 ? "< 1 menit" : Math.round(s / 60) + " menit";
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
export const num = v => (v === "" || v == null ? null : Number(v));
