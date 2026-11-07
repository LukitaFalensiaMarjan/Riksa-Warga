import { act, api } from "../../lib/api.js";
import { $, h, toast } from "../../lib/dom.js";
import { fmt, fmtDist, fmtDur } from "../../lib/format.js";
import { bearing, compass, dist, distToLine, getPosition, gmaps } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { addHazards, addRoutes, addShelters, cleanups, legend, meIcon, newMap, tip } from "../../lib/map.js";
import { store } from "../../lib/store.js";
import { badge } from "../../lib/ui.js";

// ---------- Peta evakuasi & navigasi ----------
export async function viewMapNav(box, ctx) {
  const [shelters, routes, hazards, res] = await Promise.all([
    api("GET", "/shelters"), api("GET", "/evacuation-routes"), api("GET", "/road-conditions"),
    api("GET", "/me/resident").catch(() => null)]);
  let map = null, meMarker = null, accCircle = null, myPos = null, routeLayer = null, watchId = null, chosen = null;
  const status = h("div", { class: "muted small-text" }, "Posisi belum ditentukan.");
  const results = h("div"), navBox = h("div");
  const setPos = (p, why) => {
    myPos = [p[0], p[1]];
    status.textContent = `Posisi: ${why} (${p[0].toFixed(5)}, ${p[1].toFixed(5)})${p[2] ? " · akurasi ±" + Math.round(p[2]) + " m" : ""}`;
    if (!map) return;
    meMarker ? meMarker.setLatLng(myPos) : (meMarker = L.marker(myPos, { icon: meIcon(), zIndexOffset: 1000 }).addTo(map).bindTooltip(tip("Posisi saya")));
    if (p[2]) { accCircle ? accCircle.setLatLng(myPos).setRadius(p[2]) : (accCircle = L.circle(myPos, { radius: p[2], color: "#0a64b8", weight: 1, fillOpacity: .08 }).addTo(map)); }
  };
  const usable = shelters.filter(s => s.is_verified && ["tersedia", "terbatas"].includes(s.status));

  function drawOption(o, fromCache) {
    chosen = o;
    if (routeLayer) routeLayer.remove();
    if (map) { routeLayer = L.polyline(o.points, { color: "#0a64b8", weight: 7, opacity: .85 }).addTo(map); map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] }); }
    [...results.querySelectorAll(".route-opt")].forEach(el => el.classList.toggle("on", el.dataset.sid === String(o.shelter.id)));
    navBox.replaceChildren(h("div", { class: "card" },
      h("h3", {}, `Ke ${o.shelter.name}`),
      h("div", { class: "btns", style: "margin-bottom:10px" },
        badge(o.label, o.source === "osrm" ? "b-warn" : "b-bad"), fromCache ? badge("RUTE TERSIMPAN (OFFLINE)", "b-sim") : null),
      o.warnings.map(w => h("div", { class: "notice bad" }, "⚠ " + w)),
      h("p", {}, h("b", {}, fmtDist(o.distance_m)), " · ±", fmtDur(o.duration_s), " jalan kaki"),
      h("ol", { class: "turns" }, o.steps.map(s => h("li", {}, s))),
      h("div", { class: "btns", style: "margin-top:12px" },
        h("button", { class: "teal", onclick: startNav }, "Mulai navigasi"),
        h("a", { href: gmaps(o.shelter.lat, o.shelter.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec", type: "button" }, "Google Maps"))),
      h("div", { id: "navlive" })));
  }
  function renderOptions(data, fromCache) {
    results.replaceChildren(h("div", {},
      fromCache ? h("div", { class: "notice warn" }, `Offline: menampilkan rute yang dihitung ${fmt(fromCache)}. Kondisi jalan bisa sudah berubah — utamakan rute resmi & arahan petugas.`) : null,
      h("div", { class: "notice" }, data.note),
      data.options.length ? data.options.map(o => h("div", { class: "route-opt", "data-sid": o.shelter.id, onclick: () => drawOption(o, fromCache) },
        h("b", {}, o.shelter.name), " ", o.warnings.length ? badge(`${o.warnings.length} peringatan`, "b-bad") : badge("tanpa titik bahaya tercatat", "b-ok"),
        h("div", { class: "muted small-text" }, `${fmtDist(o.distance_m)} · ±${fmtDur(o.duration_s)} · ${o.source === "osrm" ? "rute jalan" : "garis lurus"}`)))
        : h("p", { class: "muted" }, "Tidak ada shelter terverifikasi yang tersedia.")));
    if (data.options[0]) drawOption(data.options[0], fromCache);
  }
  const findRoute = act(async () => {
    if (!myPos) {
      try { setPos(await getPosition(), "GPS"); }
      catch (e) {
        if (res?.home_lat != null) { setPos([res.home_lat, res.home_lng], "lokasi rumah"); toast(e.message + " — memakai lokasi rumah", true); }
        else throw new Error(e.message + ". Ketuk peta untuk menentukan posisi.");
      }
    }
    try {
      const data = await api("GET", `/routing/shelter?lat=${myPos[0]}&lng=${myPos[1]}`);
      store.set("rw_last_route", { at: new Date().toISOString(), data });
      renderOptions(data, null);
    } catch (e) {
      if (!e.offline) throw e;
      const saved = store.get("rw_last_route");
      if (saved) renderOptions(saved.data, saved.at);
      else compassOnly();
    }
  });
  function compassOnly() {
    const near = usable.map(s => ({ s, d: dist(myPos, [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0];
    if (!near) return results.replaceChildren(h("div", { class: "notice bad" }, "Offline dan belum ada data shelter tersimpan."));
    results.replaceChildren(h("div", { class: "notice warn" }, "Offline & belum ada rute tersimpan: pakai arah kompas ke shelter terdekat dan rute resmi di peta."));
    drawOption({ shelter: near.s, points: [myPos, [near.s.lat, near.s.lng]], distance_m: near.d, duration_s: near.d / 1.2, source: "garis_lurus",
      label: "Garis lurus (offline) — hanya petunjuk arah", warnings: [], steps: [`Menuju ${compass(bearing(myPos, [near.s.lat, near.s.lng]))} sejauh ±${fmtDist(near.d)}`] }, new Date().toISOString());
  }
  function navUpdate(p) {
    setPos(p, "GPS langsung");
    const live = $("#navlive"); if (!live || !chosen) return;
    const dest = [chosen.shelter.lat, chosen.shelter.lng];
    const d = dist(myPos, dest), b = bearing(myPos, dest), off = distToLine(myPos, chosen.points);
    const arrow = h("div", { class: "arrow", style: `transform:rotate(${b}deg)` }, icon("arrow"));
    live.replaceChildren(h("div", { class: "card flat", style: "margin:12px 0 0;background:var(--soft)" },
      h("div", { class: "navpanel" }, arrow, h("div", {},
        h("div", { style: "font-size:20px;font-weight:800;color:var(--navy)" }, d < 30 ? "Anda sudah di shelter" : `±${fmtDist(d)} lagi`),
        h("div", { class: "muted" }, `Arah ${Math.round(b)}° (${compass(b)}) dari utara · akurasi GPS ±${Math.round(p[2] || 0)} m`),
        off > 50 ? h("div", { class: "err", style: "font-weight:700" }, `Anda ±${fmtDist(off)} di luar garis rute`) : null,
        d < 30 ? h("div", { style: "font-weight:700;color:var(--ok)" }, "Lapor ke petugas posko untuk check-in.") : null)),
      h("button", { class: "danger small", style: "margin-top:10px", onclick: stopNav }, "Hentikan navigasi")));
    if (map) map.panTo(myPos);
  }
  function startNav() {
    if (!navigator.geolocation) return toast("GPS tidak tersedia", true);
    stopNav();
    watchId = navigator.geolocation.watchPosition(pos => navUpdate([pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy]),
      () => toast("GPS tidak didapat. Pastikan izin lokasi aktif.", true), { enableHighAccuracy: true, maximumAge: 4000, timeout: 15000 });
    toast("Navigasi dimulai — layar mengikuti posisi Anda");
  }
  function stopNav() { if (watchId != null) navigator.geolocation.clearWatch(watchId); watchId = null; }
  cleanups.push(stopNav);

  box.append(h("h2", {}, "Peta Evakuasi"),
    h("div", { class: "cols-2" },
      h("div", { class: "card" },
        legend([["#0f9d6b", "Shelter"], ["#b91c1c", "Titik bahaya"], ["#0f9d6b", "Rute resmi terverifikasi (garis hijau)"], ["#0a64b8", "Rute dihitung / posisi saya"]]),
        h("div", { id: "navmap", class: "map tall" }),
        h("p", { class: "muted small-text" }, "Peta yang pernah Anda buka tersimpan otomatis untuk dipakai saat offline. Buka & geser peta di sekitar rumah dan shelter selagi online.")),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "Cari rute ke shelter"), status,
          h("div", { class: "btns", style: "margin:10px 0" },
            h("button", { class: "sec", onclick: act(async () => { setPos(await getPosition(), "GPS"); }) }, "Pakai GPS"),
            res?.home_lat != null ? h("button", { class: "sec", onclick: () => setPos([res.home_lat, res.home_lng], "lokasi rumah") }, "Dari rumah") : null,
            h("button", { onclick: findRoute }, "Cari rute terdekat")),
          h("p", { class: "muted small-text" }, "Atau ketuk peta untuk menentukan posisi. Lokasi dikirim ke layanan rute OSRM hanya untuk menghitung jalan."), results),
        navBox)));
  ctx.post(() => {
    map = newMap($("#navmap"));
    if (!map) return;
    addRoutes(map, routes); addHazards(map, hazards); addShelters(map, shelters);
    map.on("click", e => setPos([e.latlng.lat, e.latlng.lng], "dipilih di peta"));
    if (res?.home_lat != null) setPos([res.home_lat, res.home_lng], "lokasi rumah");
  });
}
