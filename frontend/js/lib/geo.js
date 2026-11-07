export const rad = d => d * Math.PI / 180;
export function dist(a, b) {
  const dl = rad(b[0] - a[0]), dg = rad(b[1] - a[1]);
  const x = Math.sin(dl / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dg / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(x));
}
export function bearing(a, b) {
  const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
  const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) - Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
export const compass = deg => ["utara", "timur laut", "timur", "tenggara", "selatan", "barat daya", "barat", "barat laut"][Math.round(deg / 45) % 8];
export function distToLine(p, pts) {
  if (pts.length < 2) return pts.length ? dist(p, pts[0]) : Infinity;
  let best = Infinity;
  const k = Math.cos(rad(p[0]));
  for (let i = 0; i < pts.length - 1; i++) {
    const [ay, ax] = [pts[i][0], pts[i][1] * k], [by, bx] = [pts[i + 1][0], pts[i + 1][1] * k], [py, px] = [p[0], p[1] * k];
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
    best = Math.min(best, dist(p, [ay + t * dy, (ax + t * dx) / k]));
  }
  return best;
}
export function getPosition(timeout = 9000) {
  return new Promise((ok, fail) => {
    if (!navigator.geolocation) return fail(new Error("Perangkat tidak mendukung GPS"));
    navigator.geolocation.getCurrentPosition(p => ok([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
      e => fail(new Error(e.code === 1 ? "Izin lokasi ditolak" : "Lokasi GPS belum didapat")),
      { enableHighAccuracy: true, timeout, maximumAge: 30000 });
  });
}
export const gmaps = (lat, lng) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=walking`;
