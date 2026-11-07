import { PRESETS, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h } from "../../lib/dom.js";
import { num, uid } from "../../lib/format.js";
import { getPosition } from "../../lib/geo.js";
import { newMap, pinIcon } from "../../lib/map.js";
import { postOrQueue } from "../../lib/offline.js";
import { field, opts, regionOptions } from "../../lib/ui.js";
import { me } from "../../state.js";

// ---------- Lapor kejadian ----------
export async function viewReport(box, ctx) {
  const regions = await api("GET", "/regions/lookup");
  const hazard = h("select", {}, opts([["banjir", "Banjir"]]));
  const desc = h("textarea", { placeholder: "Apa yang terlihat? (min. 5 karakter)" });
  const region = h("select", {}, regionOptions(regions, me.region_id, ["rt", "rw", "kelurahan"]));
  const lat = h("input", { type: "number", step: "any", placeholder: "lat" });
  const lng = h("input", { type: "number", step: "any", placeholder: "lng" });
  let gps = null, pin = null, map = null;
  const put = (la, ln) => {
    lat.value = (+la).toFixed(6); lng.value = (+ln).toFixed(6);
    if (map) { pin ? pin.setLatLng([la, ln]) : (pin = L.marker([la, ln], { icon: pinIcon("#dc2626", "!") }).addTo(map)); map.panTo([la, ln]); }
  };
  const preset = h("select", {
    onchange: ev => {
      const p = PRESETS[ev.target.value]; if (!p) return;
      gps = null; put(p[1], p[2]);
      const ro = [...region.options].find(o => o.textContent.startsWith(p[3]));
      if (ro) region.value = ro.value;
    },
  }, h("option", { value: "" }, "— titik contoh demo —"), PRESETS.map((p, i) => h("option", { value: i }, p[0])));
  const sim = h("input", { type: "checkbox" });
  const sensor = h("input", { type: "checkbox" });
  const photo = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
  const out = h("div");
  const submit = act(async () => {
    const body = {
      hazard: hazard.value, description: desc.value.trim(), region_id: Number(region.value),
      lat: num(lat.value), lng: num(lng.value), source_mode: sim.checked ? "simulation" : "real",
      reported_at: new Date().toISOString(), client_ref: uid(),
    };
    if (gps) { body.gps_lat = gps[0]; body.gps_lng = gps[1]; }
    if (me.role === "pos_pantau" && sensor.checked) body.from_sensor = true;
    if (body.lat == null || body.lng == null) throw new Error("Pilih lokasi di peta, pakai GPS, atau isi koordinat");
    if (body.description.length < 5) throw new Error("Deskripsi minimal 5 karakter");
    const r = await postOrQueue("/reports", body, `Laporan ${body.hazard}`);
    if (!r.sent) { out.replaceChildren(h("div", { class: "notice warn" }, "Laporan disimpan di perangkat dan akan dikirim saat online. Foto hanya bisa dikirim saat online.")); return; }
    let msg = `Laporan #${r.data.id} diterima — status: ${lab(r.data.status)}${r.data.incident_id ? `, kejadian #${r.data.incident_id}` : ""}.`;
    if (photo.files[0]) {
      const fd = new FormData(); fd.append("file", photo.files[0]);
      try { await api("POST", `/reports/${r.data.id}/photo`, fd); msg += " Foto terlampir."; }
      catch (e) { msg += " Foto gagal: " + e.message; }
    }
    out.replaceChildren(h("div", { class: "notice ok" }, msg));
    desc.value = ""; photo.value = "";
  });
  box.append(h("h2", {}, "Lapor Kejadian"),
    h("div", { class: "notice" }, "Pilih RT/RW tempat kejadian (bukan alamat rumah). Lokasi ini menentukan siapa yang menerima peringatan. Jangan mendekati api atau arus air demi foto."),
    h("div", { class: "cols-2" },
      h("div", { class: "card" },
        h("div", { class: "row" }, field("Jenis kejadian", hazard)),
        field("Deskripsi", desc),
        field("Lokasi kejadian (RT/RW)", region),
        h("div", { class: "row" }, field("Titik contoh demo", preset), h("button", {
          class: "sec", type: "button",
          onclick: act(async () => { const p = await getPosition(); gps = [p[0], p[1]]; put(p[0], p[1]); }, "Lokasi GPS dipakai"),
        }, "Pakai GPS saya")),
        h("div", { class: "row" }, field("Latitude", lat), field("Longitude", lng)),
        field("Foto (opsional, JPG/PNG/WebP, maks. 5 MB)", photo),
        h("label", { class: "chk" }, sim, "Data simulasi (demo) — diberi label SIMULASI"),
        me.role === "pos_pantau" ? h("label", { class: "chk" }, sensor, "Ini indikasi dari sensor pos pantau") : null,
        h("button", { onclick: submit, style: "width:100%;margin-top:6px" }, "Kirim laporan"), out),
      h("div", { class: "card" }, h("h3", {}, "Ketuk peta untuk menaruh pin lokasi"), h("div", { id: "mapslot", class: "map tall" }))));
  ctx.post(() => {
    map = newMap($("#mapslot"));
    if (map) map.on("click", e => { gps = null; put(e.latlng.lat, e.latlng.lng); });
  });
}
