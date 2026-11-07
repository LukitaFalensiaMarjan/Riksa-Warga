import { PRESETS, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { num, uid } from "../../lib/format.js";
import { getPosition } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { newMap, pinIcon } from "../../lib/map.js";
import { postOrQueue } from "../../lib/offline.js";
import { field, regionOptions } from "../../lib/ui.js";
import { me } from "../../state.js";

// ---------- Lapor kejadian (warga): tiga langkah bernomor ----------
const QUICK = ["Air masuk rumah", "Air naik cepat", "Jalan tergenang", "Arus deras", "Ada warga terjebak"];

export async function viewWargaReport(box, ctx) {
  const regions = await api("GET", "/regions/lookup");
  let cond = null, gps = null, pin = null, map = null, located = false;

  const region = h("select", {}, regionOptions(regions, me.region_id, ["rt", "rw", "kelurahan"]));
  const lat = h("input", { type: "number", step: "any", placeholder: "lat" }), lng = h("input", { type: "number", step: "any", placeholder: "lng" });
  const desc = h("textarea", { placeholder: "Apa yang terlihat? Contoh: air setinggi lutut di depan masjid" });
  const photo = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true });
  const prev = h("div", { class: "photo-prev" });
  const out = h("div");
  const send = h("button", { class: "send", disabled: true }, "Kirim laporan");

  const locStat = h("div", { class: "loc-stat" });
  const count = h("div", { class: "count" });
  const steps = ["Jenis", "Lokasi", "Detail"].map((t, i) => h("a", { href: "#", onclick: ev => { ev.preventDefault(); $("#ws" + (i + 1)).scrollIntoView({ behavior: "smooth", block: "start" }); } }, h("b", {}, i + 1), h("span", {}, t)));
  const refresh = () => {
    located = lat.value !== "" && lng.value !== "";
    locStat.className = "loc-stat" + (located ? " ok" : "");
    locStat.replaceChildren(icon(located ? "check" : "pin"), located ? `Lokasi terpilih (${(+lat.value).toFixed(4)}, ${(+lng.value).toFixed(4)})` : "Belum ada lokasi — ketuk peta atau pakai GPS");
    const n = desc.value.trim().length;
    count.textContent = n >= 5 ? `${n} karakter` : `${n}/5 karakter minimum`; count.className = "count" + (n >= 5 ? " ok" : "");
    const ok = [!!cond, located, n >= 5];
    steps.forEach((s, i) => s.classList.toggle("done", ok[i]));
    send.disabled = !ok.every(Boolean);
  };
  const put = (la, ln) => {
    lat.value = (+la).toFixed(6); lng.value = (+ln).toFixed(6);
    if (map) { pin ? pin.setLatLng([la, ln]) : (pin = L.marker([la, ln], { icon: pinIcon("#dc2626", "!") }).addTo(map)); map.panTo([la, ln]); }
    refresh();
  };
  lat.oninput = lng.oninput = desc.oninput = refresh;

  // langkah 1: kondisi banjir
  const tiles = [["Genangan", "Air naik di jalan atau halaman", "banjir"], ["Masuk rumah", "Air sudah masuk bangunan", "logistik"], ["Arus deras", "Aliran kuat dan berbahaya", "rute"], ["Warga terjebak", "Perlu bantuan segera", "sos"]].map(([t, d, ic]) =>
    h("button", { type: "button", class: "tile t-banjir", onclick: ev => { cond = t; tiles.forEach(b => b.classList.toggle("on", b === ev.currentTarget)); refresh(); } },
      icon(ic), h("b", {}, t), h("small", {}, d)));

  // langkah 3
  const quick = h("div", { class: "quick" });
  const renderQuick = () => quick.replaceChildren(...QUICK.map(t => h("button", { type: "button", onclick: () => { desc.value = desc.value ? desc.value.replace(/\s*$/, ". ") + t : t; refresh(); desc.focus(); } }, "+ " + t)));
  renderQuick();
  photo.onchange = () => {
    const f = photo.files[0];
    prev.replaceChildren(f ? h("img", { src: URL.createObjectURL(f), alt: "Pratinjau foto" }) : "");
  };
  const preset = h("select", {
    onchange: ev => {
      const p = PRESETS[ev.target.value]; if (!p) return;
      gps = null; put(p[1], p[2]);
      const ro = [...region.options].find(o => o.textContent.startsWith(p[3])); if (ro) region.value = ro.value;
    },
  }, h("option", { value: "" }, "— titik contoh demo —"), PRESETS.map((p, i) => h("option", { value: i }, p[0])));
  const sim = h("input", { type: "checkbox" });

  const reset = () => {
    cond = null; tiles.forEach(b => b.classList.remove("on")); desc.value = ""; photo.value = ""; prev.replaceChildren(); quick.replaceChildren();
    lat.value = lng.value = ""; if (pin) { pin.remove(); pin = null; } gps = null; out.replaceChildren(); form.hidden = false; refresh();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  send.onclick = act(async () => {
    const body = {
      hazard: "banjir", description: `[${cond}] ` + desc.value.trim(), region_id: Number(region.value), lat: num(lat.value), lng: num(lng.value),
      source_mode: sim.checked ? "simulation" : "real", reported_at: new Date().toISOString(), client_ref: uid(),
    };
    if (gps) { body.gps_lat = gps[0]; body.gps_lng = gps[1]; }
    const r = await postOrQueue("/reports", body, `Laporan banjir`);
    let title = "Laporan terkirim", sub;
    if (!r.sent) { title = "Disimpan di perangkat"; sub = "Tidak ada sinyal. Laporan otomatis terkirim saat online. Foto hanya bisa dikirim saat online."; }
    else {
      sub = `Laporan #${r.data.id} diterima — status: ${lab(r.data.status)}${r.data.incident_id ? `, masuk kejadian #${r.data.incident_id}` : ""}.`;
      if (photo.files[0]) {
        const fd = new FormData(); fd.append("file", photo.files[0]);
        try { await api("POST", `/reports/${r.data.id}/photo`, fd); sub += " Foto terlampir."; } catch (e) { sub += " Foto gagal: " + e.message; }
      }
    }
    form.hidden = true;
    out.replaceChildren(h("div", { class: "card success" },
      (() => { const d = h("div"); d.innerHTML = '<svg class="tick" viewBox="0 0 52 52" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="26" cy="26" r="24"/><path d="M15 27l8 8 15-17"/></svg>'; return d.firstChild; })(),
      h("h3", {}, title), h("p", {}, sub),
      h("div", { class: "btns", style: "justify-content:center" }, h("button", { onclick: () => { location.hash = "#mine"; } }, "Pantau laporan saya"), h("button", { class: "sec", onclick: reset }, "Buat laporan lain"))));
  });

  const form = h("div", {},
    h("div", { class: "stepbar" }, steps),
    h("div", { class: "card", id: "ws1" }, h("div", { class: "sec-t" }, h("b", {}, 1), h("h3", {}, "Bagaimana kondisi banjirnya?")), h("div", { class: "tiles" }, tiles)),
    h("div", { class: "cols-2", id: "ws2" },
      h("div", { class: "card" }, h("div", { class: "sec-t" }, h("b", {}, 2), h("h3", {}, "Di mana kejadiannya?")),
        field("RT/RW tempat kejadian (bukan alamat rumah)", region), locStat,
        h("button", { class: "sec", type: "button", style: "width:100%", onclick: act(async () => { const p = await getPosition(); gps = [p[0], p[1]]; put(p[0], p[1]); }, "Lokasi GPS dipakai") }, icon("gps"), " Pakai lokasi GPS saya"),
        h("details", { style: "margin-top:12px" }, h("summary", {}, "Isi koordinat / titik contoh demo"),
          h("div", { class: "row" }, field("Latitude", lat), field("Longitude", lng)), field("Titik contoh demo", preset))),
      h("div", { class: "card map-card" }, h("div", { class: "sec-t" }, h("h3", {}, "Ketuk peta untuk menaruh pin")), h("div", { id: "mapslot", class: "map" }))),
    h("div", { class: "card", id: "ws3" }, h("div", { class: "sec-t" }, h("b", {}, 3), h("h3", {}, "Ceritakan singkat")),
      quick, desc, count,
      h("div", { class: "photo-row" }, h("button", { type: "button", class: "sec small", onclick: () => photo.click(), title: "JPG/PNG/WebP, maks. 5 MB. Jangan mendekati api atau arus air demi foto." }, icon("camera"), " Tambah foto (opsional)"), photo, prev),
      h("label", { class: "chk", style: "margin-top:12px" }, sim, "Data simulasi (demo) — diberi label SIMULASI"),
      send));

  box.append(h("div", { class: "w-head" }, h("h2", {}, "Lapor Kejadian"), h("p", {}, "Tiga langkah singkat. Lokasi laporan menentukan siapa yang menerima peringatan.")), form, out);
  refresh();
  ctx.post(() => {
    map = newMap($("#mapslot"));
    if (map) map.on("click", e => { gps = null; put(e.latlng.lat, e.latlng.lng); });
  });
}
