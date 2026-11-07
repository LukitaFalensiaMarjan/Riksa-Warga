"use strict";
/* Riksa Warga PRD v2 — tampilan tambahan/pengganti. Dimuat SETELAH app.js (fungsi bernama sama menimpa yang lama;
   TABS dimutasi di sini). Semua data pengguna dirender lewat h() (textContent), bukan innerHTML. */

Object.assign(LABEL, {
  diduga_butuh_bantuan: "Diduga Butuh Bantuan", tiba_di_titik_aman: "Sudah Evakuasi",
  sesuai: "Sesuai", sebagian: "Sebagian sesuai", tidak_sesuai: "Tidak sesuai", data_kurang: "Data kurang",
  rendah: "Rendah", sedang: "Sedang", tinggi: "Tinggi", tim_sar: "Tim SAR", pos_pantau: "Pos Pantau",
});
delete ROLE_LABEL.relawan; delete ROLE_LABEL.petugas;
Object.assign(ICONS, {
  prediksi: "M3 17l6-6 4 4 8-8M14 7h7v7",
  keluarga: "M17 20v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M10 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM21 20v-2a3 3 0 0 0-2-2.8M16 3.2a3 3 0 0 1 0 5.6",
});
const RISK_HERO = { rendah: "", sedang: "l-waspada", tinggi: "l-evakuasi" };
const RISK_BADGE = { rendah: "b-ok", sedang: "b-waspada", tinggi: "b-evakuasi" };
const ROLE_NAMES = ["warga", "koordinator", "pos_pantau", "tim_sar", "admin"];

function tabsFor(role) {
  if (role === "admin") return ["admin"];
  if (role === "koordinator") return ["dashboard", "live", "prediksi", "prioritas", "tugas", "residents", "keluarga", "petarute", "shelters", "alerts"];
  if (role === "tim_sar") return ["tugasku", "peta", "live", "prediksi", "shelters", "alerts"];
  if (role === "pos_pantau") return ["live", "prediksi", "reports", "incidents", "peta", "alerts", "shelters"];
  return ["beranda", "live", "prediksi", "peta", "mine", "alerts", "shelters", "lapor"];
}

const modal = (title, ...content) => {
  const close = () => ov.remove();
  const ov = h("div", { style: "position:fixed;inset:0;background:rgba(11,58,110,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:14px", onclick: e => { if (e.target === ov) close(); } },
    h("div", { class: "card", style: "max-width:640px;width:100%;max-height:92vh;overflow:auto;margin:0" },
      h("div", { style: "display:flex;justify-content:space-between;gap:10px;align-items:start" }, h("h3", { style: "margin:0 0 10px" }, title), h("button", { class: "ghost", onclick: close }, "✕")),
      ...content));
  document.body.append(ov);
  return { close, ov };
};

// ---------- profil, kanal kontak, SMS, izin lokasi ----------
function profile(box) {
  const tg = h("input", { value: me.telegram_chat_id || "", placeholder: "mis. 1949754174", inputmode: "numeric" });
  const ph = h("input", { value: me.phone || "", placeholder: "08123456789", inputmode: "tel" });
  const sms = h("input", { type: "checkbox", checked: !!me.sms_opt_in });
  const loc = h("div");
  const card = h("div", { class: "card accent" },
    h("h3", {}, "Profil & kanal peringatan"),
    h("p", { class: "muted small-text" }, "Telegram: kirim /start ke bot Riksa Warga lebih dulu. SMS: hanya dikirim untuk peristiwa berat ke nomor yang Anda setujui."),
    h("div", { class: "row" }, field("Telegram chat ID", tg), field("Nomor ponsel (SMS)", ph)),
    h("label", { class: "chk" }, sms, "Saya setuju menerima SMS peringatan dari Riksa Warga (mungkin berbayar menurut operator)"),
    h("div", { class: "btns" },
      h("button", { onclick: act(async () => { me = await api("PATCH", "/auth/me", { telegram_chat_id: tg.value.trim(), phone: ph.value.trim(), sms_opt_in: sms.checked }); sms.checked = !!me.sms_opt_in; ph.value = me.phone || ""; }, "Profil tersimpan") }, "Simpan"),
      h("button", { class: "ghost", onclick: () => box.replaceChildren() }, "Tutup")),
    loc);
  box.replaceChildren(h("main", { style: "padding-bottom:0" }, card));
  if (me.role !== "warga") return;
  api("GET", "/me/resident").then(r => {
    const on = r.location_consent_at && !r.location_revoked_at;
    loc.replaceChildren(h("hr", { style: "border:0;border-top:1px solid var(--line);margin:14px 0" }),
      h("h3", {}, "Izin lokasi"),
      on ? h("p", {}, badge("AKTIF", "b-ok"), ` sejak ${fmt(r.location_consent_at)}. Lokasi hanya dipakai saat Mode Bencana. Anda bisa mencabutnya kapan saja.`)
        : h("p", {}, badge("BELUM ADA", "b-warn"), " Berikan izin sekali agar saat bencana tim dapat menemukan Anda bila butuh bantuan."),
      h("div", { class: "btns" },
        on ? h("button", { class: "danger small", onclick: act(async () => { await api("DELETE", "/me/location/consent"); profile(box); }, "Izin lokasi dicabut, lokasi dihapus") }, "Cabut izin lokasi")
          : h("button", { class: "teal small", onclick: act(async () => { await api("POST", "/me/location/consent", { agree: true, version: "v1" }); profile(box); }, "Izin lokasi disimpan") }, "Saya setuju (cukup sekali)"),
        on ? h("button", { class: "sec small", onclick: act(async () => { const p = await getPosition(); await api("POST", "/me/location", { lat: p[0], lng: p[1], kind: "rumah" }); }, "Lokasi rumah disimpan dari GPS") }, "Simpan lokasi rumah (GPS)") : null));
  }).catch(() => { /* offline: tampilan dasar saja */ });
}

// ---------- beranda warga: Mode Bencana, izin lokasi, keluarga (disisipkan di atas viewHome lama) ----------
async function homeExtras(box) {
  let res = null, mode = { active: false };
  try { res = await api("GET", "/me/resident"); } catch { return; }
  try { mode = await api("GET", "/me/mode"); } catch { /* offline */ }
  const consented = !!res.location_consent_at && !res.location_revoked_at;
  if (mode.active) {
    if (consented) {  // lokasi dikirim saat aplikasi terbuka selama Mode Bencana
      getPosition(4000).then(p => postOrQueue("/me/location", { lat: p[0], lng: p[1] }, "Lokasi saya")).catch(() => { /* izin GPS ditolak */ });
    }
  }
  if (!consented) {
    box.append(h("div", { class: "card accent" }, h("h3", {}, "Izin lokasi (cukup sekali)"),
      h("p", { class: "muted" }, "Lokasi Anda hanya dipakai saat Mode Bencana, hanya terlihat koordinator wilayah Anda dan Tim SAR (bila Anda butuh bantuan), dan tidak pernah masuk pesan Telegram/SMS atau peta publik. Bisa dicabut kapan saja di Profil."),
      h("button", { class: "teal", onclick: act(async () => { await api("POST", "/me/location/consent", { agree: true, version: "v1" }); await reload(); }, "Izin lokasi disimpan") }, "Saya setuju")));
  }
  try {
    const fam = await api("GET", "/me/family");
    if (fam.length) box.append(h("div", { class: "card" }, h("h3", {}, "Data keluarga saya (dicatat koordinator)"),
      table([{ label: "Nama", key: "name" }, { label: "Hubungan", render: m => m.relation || "-" }, { label: "Usia", render: m => m.age ?? "-" },
        { label: "Kondisi", render: m => m.vulnerability.length ? m.vulnerability.join(", ") : "-" }], fam)));
  } catch { /* abaikan */ }
}

const _viewHomeV1 = viewHome;
TABS.beranda.render = async (box, ctx) => {
  const top = h("div");
  await _viewHomeV1(box, ctx);
  await homeExtras(top);
  box.prepend(top);
  // Bersihkan hero ganda jika ada
  const heroes = box.querySelectorAll(".hero");
  if (heroes.length > 1) {
    for (let i = 1; i < heroes.length; i++) heroes[i].remove();
  }
};

// ---------- cuaca & prediksi ----------
function rainChart(hours) {
  const W = 560, H = 120, P = 24, NS = "http://www.w3.org/2000/svg";
  const el = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart" });
  const max = Math.max(5, ...hours.map(x => x.mm)) * 1.15, bw = (W - 2 * P) / Math.max(1, hours.length);
  hours.forEach((x, i) => {
    const bh = (x.mm / max) * (H - 2 * P);
    svg.append(el("rect", { x: P + i * bw + 1, y: H - P - bh, width: Math.max(2, bw - 2), height: bh, fill: x.mm >= 7 ? "#dc2626" : x.mm >= 2 ? "#d97706" : "#0a64b8", rx: 2 }));
    if (i % 3 === 0) svg.append(el("text", { x: P + i * bw, y: H - 6, "font-size": 10, fill: "#5d6b7d" }, utc(x.at).toLocaleTimeString("id-ID", { timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit" })));
  });
  svg.append(el("text", { x: P, y: 12, "font-size": 11, fill: "#142235", "font-weight": 700 }, `Prakiraan hujan 24 jam (mm/jam) — puncak ${Math.max(0, ...hours.map(x => x.mm))} mm`));
  return svg;
}

function forecastCard(fc, full = false) {
  const c = fc.city, r = fc.rain;
  return h("div", {},
    h("div", { class: "hero " + (RISK_HERO[c.risk] || ""), style: "margin-bottom:12px" },
      h("small", {}, `PREDIKSI POTENSI BANJIR · ±${c.window_hours} JAM KE DEPAN · KEYAKINAN ${c.confidence.toUpperCase()}`),
      h("h1", {}, `Potensi banjir: ${c.risk.toUpperCase()}`),
      h("p", {}, c.station ? `Pos paling berisiko: ${c.station}. ` : "", "Ini PERKIRAAN bantu, bukan deteksi banjir."),
      h("ul", { style: "margin:8px 0 0;padding-left:18px" }, c.reasons.slice(0, full ? 8 : 3).map(x => h("li", {}, x)))),
    r.available && r.hours.length ? h("div", { class: "card flat" }, rainChart(r.hours),
      h("div", { class: "muted small-text" }, `3 jam: ${r.next3_mm} mm · 6 jam: ${r.next6_mm} mm · 24 jam: ${r.next24_mm} mm · sumber ${r.source}${r.stale ? " · KEDALUWARSA" : ""} · diambil ${fmt(r.fetched_at)}`))
      : h("div", { class: "notice warn" }, "Prakiraan hujan tidak tersedia (sumber gagal diakses); keyakinan prediksi diturunkan."),
    full ? h("div", { class: "card" }, h("h3", {}, "Per pos pantau"), table([
      { label: "Pos", render: s => [h("b", {}, s.name), h("div", { class: "muted small-text" }, s.river || "")] },
      { label: "Risiko", render: s => badge(s.risk.toUpperCase(), RISK_BADGE[s.risk]) },
      { label: "Jendela", render: s => `±${s.window_hours} jam` }, { label: "Keyakinan", key: "confidence" },
      { label: "Sungai", render: s => `${s.condition.toUpperCase()} · tren ${s.trend.replaceAll("_", " ")}` },
      { label: "Estimasi", render: s => s.eta_to_threshold ? `bisa mencapai ${s.eta_to_threshold.to} dalam ${s.eta_to_threshold.minutes_low}–${s.eta_to_threshold.minutes_high} menit` : "-" },
      { label: "Alasan", render: s => h("ul", { style: "margin:0;padding-left:16px" }, s.reasons.map(x => h("li", {}, x))) },
    ], fc.stations)) : null);
}

async function viewForecast(box) {
  const fc = await api("GET", "/forecast");
  box.append(h("h2", {}, "Prediksi Banjir"), h("div", { class: "notice warn" }, fc.label), forecastCard(fc, true));
}

// ---------- peta Tim SAR ----------
async function viewSarMap(box, ctx) {
  const [d, shelters] = await Promise.all([api("GET", "/evacuation/rescue-targets"), api("GET", "/shelters")]);
  let myPos = null;
  try { myPos = (await getPosition(3500)).slice(0, 2); } catch { /* tanpa GPS: jarak tidak dihitung */ }
  let map = null, routeLayer = null;
  const nav = h("div");
  const items = d.items.map(x => ({ ...x, d: myPos && x.lat != null ? dist(myPos, [x.lat, x.lng]) : null }))
    .sort((a, b) => b.score - a.score || (a.d ?? 1e9) - (b.d ?? 1e9));
  const route = x => act(async () => {
    if (!myPos) throw new Error("Posisi Anda belum diketahui. Aktifkan GPS.");
    const r = await api("GET", `/routing/point?lat=${myPos[0]}&lng=${myPos[1]}&to_lat=${x.lat}&to_lng=${x.lng}`);
    if (routeLayer) routeLayer.remove();
    if (map) { routeLayer = L.polyline(r.points, { color: "#0a64b8", weight: 7, opacity: .85 }).addTo(map); map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] }); }
    nav.replaceChildren(h("div", { class: "card" }, h("h3", {}, `Rute ke ${x.name}`),
      badge(r.label, r.source === "osrm" ? "b-warn" : "b-bad"), r.warnings.map(w => h("div", { class: "notice bad" }, "⚠ " + w)),
      h("p", {}, h("b", {}, fmtDist(r.distance_m)), " · ±", fmtDur(r.duration_s), " jalan kaki"), h("ol", { class: "turns" }, r.steps.map(s => h("li", {}, s)))));
  });
  box.append(h("h2", {}, "Peta Menuju Warga Butuh Bantuan"),
    h("div", { class: "notice warn" }, d.mode_active ? d.note : "Mode Bencana belum aktif: belum ada target. Peta ini terisi otomatis saat sungai Meluap / ada pengumuman Waspada+."),
    h("div", { class: "grid" }, ["kritis", "tinggi", "sedang", "rendah"].map(k => h("div", { class: "stat", style: `--c:${PRIO_COLOR[k]}` }, h("b", {}, items.filter(i => i.priority === k).length), h("span", {}, "Prioritas " + k)))),
    h("div", { class: "cols-2" },
      h("div", { class: "card" }, legend([["#dc2626", "Zona berbahaya / kritis"], ["#ea580c", "Tinggi"], ["#d97706", "Sedang"], ["#0e7c86", "Rendah"], ["#0f9d6b", "Shelter"]]), h("div", { id: "sarmap", class: "map tall" })),
      h("div", {}, h("div", { class: "card", style: "max-height:62vh;overflow:auto" }, h("h3", {}, `${items.length} warga di zona berbahaya`),
        items.length ? items.map(x => h("div", { class: "prio-item" },
          h("div", { class: "prio-score", style: `background:${PRIO_COLOR[x.priority]}` }, x.score),
          h("div", {}, h("div", { class: "btns" }, h("b", {}, x.name), prioBadge(x.priority), badge(lab(x.status), x.status === "butuh_bantuan" ? "b-bad" : "b-warn"),
            x.status === "diduga_butuh_bantuan" ? badge("DUGAAN", "b-warn") : null, x.task ? badge(`tugas #${x.task.id}`, "b-sim") : null),
            h("div", { class: "factor" }, [...(x.vulnerability || []), ...(x.family_vulnerability || []).map(v => v + " (keluarga)")].join(", ") || "tanpa catatan kerentanan"),
            h("div", { class: "factor" }, `Lokasi ${x.location_source}${x.d != null ? " · ±" + fmtDist(x.d) + " dari Anda" : ""}${x.nearest_shelter ? " · shelter " + x.nearest_shelter.name + " " + fmtDist(x.nearest_shelter.distance_m) : ""}`)),
          h("div", { class: "btns", style: "flex-direction:column" },
            h("button", { class: "small", onclick: route(x) }, "Rute"),
            h("button", { class: "sec small", onclick: () => map?.setView([x.lat, x.lng], 18) }, "Peta"),
            h("a", { href: gmaps(x.lat, x.lng), target: "_blank", rel: "noopener" }, "Maps")))) : h("div", { class: "notice ok" }, "Tidak ada warga butuh bantuan yang tercatat di zona berbahaya.")), nav)));
  ctx.post(() => {
    map = newMap($("#sarmap"));
    if (!map) return;
    addShelters(map, shelters);
    d.zones.forEach(z => L.circle([z.lat, z.lng], { radius: z.radius_m, color: "#dc2626", weight: 2, fillOpacity: .12 }).addTo(map).bindTooltip(tip(z.label || "Zona berbahaya")));
    items.forEach(x => L.marker([x.lat, x.lng], { icon: pinIcon(PRIO_COLOR[x.priority], "!", x.priority === "kritis") }).addTo(map).bindTooltip(tip(`${x.name} — ${x.priority.toUpperCase()} (${x.score}) · ${lab(x.status)}`)));
    if (myPos) L.marker(myPos, { icon: meIcon(), zIndexOffset: 1000 }).addTo(map).bindTooltip(tip("Posisi Tim SAR"));
    const pts = items.map(x => [x.lat, x.lng]).concat(d.zones.map(z => [z.lat, z.lng]));
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.4));
  });
}

// ---------- tugas Tim SAR ----------
function taskCard(t, { shelters = [], vols = [], isCoord = false, myPos = null } = {}) {
  const slot = h("div");
  const isSar = me.role === "tim_sar";
  const final = ["selesai", "gagal", "dibatalkan"].includes(t.status);
  const mine = t.assignee_id === me.id;
  const open = t.status === "baru" && !t.assignee_id;
  const post = (path, body, ok) => act(async () => { await api("POST", path, body); await reload(); }, ok);
  const ask = (q, fn) => act(async () => { const v = prompt(q); if (!v) throw new Error("batal"); await fn(v); await reload(); });
  const finishForm = () => {
    const shel = h("select", {}, h("option", { value: "" }, "— tidak ke shelter —"), shelters.map(s => h("option", { value: s.id, selected: s.id === t.shelter_id }, s.name)));
    const people = h("input", { type: "number", min: 0, value: t.people_count ?? 1 });
    const note = h("textarea", { placeholder: "Hasil penanganan (wajib)" });
    slot.replaceChildren(h("div", { class: "card flat", style: "margin:8px 0 0;background:var(--soft)" },
      h("div", { class: "row" }, field("Tiba di shelter", shel), field("Jumlah orang", people)), field("Hasil", note),
      h("button", { class: "green", onclick: act(async () => {
        await api("POST", `/tasks/${t.id}/status`, { status: "selesai", note: note.value, people_count: Number(people.value), shelter_id: num(shel.value) }); await reload();
      }, "Tugas selesai") }, "Simpan selesai")));
  };
  const reportForm = () => {
    const f = { n: h("input", { type: "number", min: 0, value: t.people_count ?? 1 }), c: h("select", {}, opts([["selamat", "Selamat"], ["luka", "Luka"], ["butuh_rujukan", "Butuh rujukan RS"]])),
      d: h("input", { placeholder: "Shelter / RS tujuan" }), o: h("input", { placeholder: "Kendala di lapangan" }), x: h("textarea", { placeholder: "Catatan" }) };
    slot.replaceChildren(h("div", { class: "card flat", style: "margin:8px 0 0;background:var(--soft)" }, h("h3", {}, "Laporan pasca-bantuan"),
      h("div", { class: "row" }, field("Jumlah orang dibantu", f.n), field("Kondisi", f.c)), field("Tujuan", f.d), field("Kendala", f.o), field("Catatan", f.x),
      h("button", { class: "teal", onclick: act(async () => { await api("POST", `/tasks/${t.id}/report`, { people_helped: Number(f.n.value), condition: f.c.value, destination: f.d.value || null, obstacles: f.o.value || null, notes: f.x.value || null }); await reload(); }, "Laporan tersimpan") }, "Kirim laporan")));
  };
  const showReport = act(async () => {
    const r = await api("GET", `/tasks/${t.id}/report`);
    slot.replaceChildren(r ? h("div", { class: "notice ok" }, `Laporan: ${r.people_helped} orang · ${r.condition.replaceAll("_", " ")} · tujuan ${r.destination || "-"} · kendala ${r.obstacles || "-"} · ${r.notes || ""}`)
      : h("div", { class: "notice warn" }, "Belum ada laporan pasca-bantuan."));
  });
  const actions = [];
  if (isSar && open) actions.push(h("button", { class: "teal", onclick: post(`/tasks/${t.id}/claim`, undefined, "Tugas diambil") }, "Ambil tugas"));
  if (isSar && mine && t.status === "menunggu_penerimaan") {
    actions.push(h("button", { class: "teal", onclick: post(`/tasks/${t.id}/status`, { status: "diterima" }, "Tugas diterima") }, "Terima"));
    actions.push(h("button", { class: "sec", onclick: ask("Alasan menolak tugas (wajib):", v => api("POST", `/tasks/${t.id}/reject`, { reason: v })) }, "Tolak"));
  }
  if (isSar && mine && t.status === "diterima") actions.push(h("button", { class: "teal", onclick: post(`/tasks/${t.id}/status`, { status: "menuju_lokasi" }, "Menuju lokasi") }, "Berangkat ke lokasi"));
  if (isSar && mine && t.status === "menuju_lokasi") actions.push(h("button", { class: "teal", onclick: post(`/tasks/${t.id}/status`, { status: "dalam_penanganan" }, "Penanganan dimulai") }, "Mulai penanganan"));
  if (isSar && mine && t.status === "dalam_penanganan") actions.push(h("button", { class: "green", onclick: finishForm }, "Selesai"));
  if (isSar && mine && ["diterima", "menuju_lokasi", "dalam_penanganan"].includes(t.status))
    actions.push(h("button", { class: "sec", onclick: ask("Alasan tidak dapat dilaksanakan (wajib):", v => api("POST", `/tasks/${t.id}/status`, { status: "gagal", note: v })) }, "Tidak dapat dilaksanakan"));
  if (isCoord && !final) actions.push(h("button", { class: "danger", onclick: ask("Alasan membatalkan (wajib):", v => api("POST", `/tasks/${t.id}/status`, { status: "dibatalkan", note: v })) }, "Batalkan tugas"));
  if (isSar && mine && ["selesai", "gagal"].includes(t.status)) actions.push(h("button", { class: "sec", onclick: reportForm }, "Buat laporan pasca-bantuan"));
  if (final && (isCoord || mine)) actions.push(h("button", { class: "ghost small", onclick: showReport }, "Lihat laporan"));
  let reassign = null;
  if (isCoord && ["baru", "menunggu_penerimaan", "diterima"].includes(t.status)) {
    const who = h("select", {}, h("option", { value: "" }, "— terbuka untuk semua Tim SAR —"), vols.map(u => h("option", { value: u.id, selected: u.id === t.assignee_id }, u.name)));
    reassign = h("div", { class: "row", style: "margin-top:8px" }, field(t.assignee_id ? "Tugaskan ulang ke" : "Tugaskan langsung ke (opsional)", who),
      h("button", { class: "sec", onclick: act(async () => { if (!who.value) throw new Error("Pilih anggota Tim SAR"); await api("POST", `/tasks/${t.id}/assign`, { assignee_id: Number(who.value) }); await reload(); }, "Tim SAR ditugaskan") }, "Simpan"));
  }
  const STEP = ["menunggu_penerimaan", "diterima", "menuju_lokasi", "dalam_penanganan", "selesai"];
  const idx = STEP.indexOf(t.status);
  return h("div", { class: `card task p-${t.priority}-b` },
    h("div", { class: "btns" }, prioBadge(t.priority), badge(t.task_type.toUpperCase(), "b-info"), badge(lab(t.status), final ? (t.status === "selesai" ? "b-ok" : "b-bad") : "b-warn"),
      h("span", { class: "muted small-text" }, `#${t.id} · ${fmt(t.created_at)}${t.assignee_name ? " · " + t.assignee_name : " · terbuka untuk Tim SAR"}`)),
    h("div", { style: "font-size:17px;font-weight:800;margin-top:8px;color:var(--navy)" }, t.resident_name || "Tugas umum"),
    (t.resident_vulnerability || []).length ? h("div", { class: "btns", style: "margin:4px 0" }, t.resident_vulnerability.map(v => badge(v.replaceAll("_", " "), "b-bad"))) : null,
    h("p", { style: "margin:6px 0" }, t.description),
    t.lat != null ? h("div", { class: "muted small-text", style: "display:flex;align-items:center;flex-wrap:wrap;gap:8px" },
      h("span", {}, `Lokasi ${t.lat.toFixed(5)}, ${t.lng.toFixed(5)}${myPos ? " · ±" + fmtDist(dist(myPos, [t.lat, t.lng])) + " dari Anda" : ""}`),
      h("button", {
        class: "teal small",
        style: "padding:2px 8px;font-size:12px;font-weight:700",
        onclick: () => {
          store.set("rw_active_task_nav", {
            resident_id: t.resident_id,
            name: t.resident_name || 'Warga Korban',
            lat: t.lat,
            lng: t.lng,
            priority: t.priority,
            vulnerability: t.resident_vulnerability || []
          });
          location.hash = "#peta";
        }
      }, "📍 Navigasi di Peta"),
      h("a", { href: gmaps(t.lat, t.lng), target: "_blank", rel: "noopener" }, "Rute (Google Maps)")) : null,
    t.result ? h("div", { class: "notice " + (t.status === "selesai" ? "ok" : "bad"), style: "margin-top:8px" }, "Hasil: " + t.result) : null,
    final || idx < 0 ? null : h("div", { class: "steps" }, STEP.map((s, i) => h("span", { class: i < idx ? "done" : i === idx ? "now" : "" }, lab(s)))),
    actions.length ? h("div", { class: "btns", style: "margin-top:8px" }, actions) : null, reassign, slot);
}

// ---------- pencocokan laporan & pengumuman ----------

async function openMatchModal(r, after) {
  const m = await api("GET", `/reports/${r.id}/match`);
  const icon_ = { ok: "✔", no: "✖", unknown: "?" }, col = { ok: "var(--ok)", no: "var(--bad)", unknown: "var(--warn)" };
  const mm = modal(`Pencocokan laporan #${r.id}`,
    h("div", { class: "hero " + ({ sesuai: "", sebagian: "l-waspada", tidak_sesuai: "l-evakuasi", data_kurang: "l-pantau" }[m.result] || ""), style: "margin-bottom:10px" },
      h("small", {}, "Hasil pencocokan (alat bantu keputusan)"), h("h1", {}, lab(m.result).toUpperCase()), h("p", {}, m.note)),
    m.checks.map(c => h("div", { style: "display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line)" },
      h("b", { style: `color:${col[c.status]};width:18px` }, icon_[c.status]), h("div", {}, h("b", {}, c.label), h("div", { class: "muted small-text" }, c.detail)))),
    h("div", { class: "btns", style: "margin-top:12px" },
      r.status === "diterima" ? h("button", { onclick: act(async () => { await api("POST", `/reports/${r.id}/verify`, { note: `Pencocokan: ${m.result}` }); mm.close(); toast("Laporan diverifikasi"); await after(); }) }, "Verifikasi laporan") : null,
      r.status === "terverifikasi" ? h("button", { class: "teal", onclick: () => { mm.close(); openBroadcastModal("", r.id); } }, "Siarkan pengumuman") : null,
      h("button", { class: "sec", onclick: () => mm.close() }, "Tutup")));
}

async function openBroadcastModal(defaultMsg = "", basisReportId = null) {
  let regions = [];
  try { regions = await api("GET", "/regions/lookup"); } catch { /* tetap bisa siaran se-kota */ }
  const level = h("select", {}, opts([["waspada", "Waspada"], ["siaga", "Siaga"], ["evakuasi", "Meluap / Evakuasi"]]));
  const msg = h("textarea", { value: defaultMsg, placeholder: "Isi pengumuman singkat dan jelas" });
  const note = h("input", { placeholder: "Dasar: pengamatan langsung (min. 10 karakter) — kosongkan bila memakai laporan terverifikasi" });
  const region = h("select", {}, h("option", { value: "" }, "Seluruh kota (semua role non-admin)"), regionOptions(regions, null, ["kelurahan", "rw", "rt"]));
  const mm = modal("Siarkan pengumuman",
    h("div", { class: "notice" }, "Diterima semua role KECUALI admin lewat aplikasi, Telegram, dan SMS (SMS hanya ke yang opt-in dan punya nomor valid). Instruksi resmi BPBD/petugas tetap diutamakan."),
    basisReportId ? h("p", {}, "Dasar: ", badge(`laporan #${basisReportId} terverifikasi`, "b-ok")) : null,
    field("Tingkat", level), field("Wilayah sasaran", region), field("Pesan", msg), basisReportId ? null : field("Dasar pengamatan", note),
    h("div", { class: "btns" }, h("button", {
      class: "danger", onclick: act(async () => {
        await api("POST", "/alerts/broadcast", { message: msg.value, level: level.value, region_id: num(region.value), basis_report_id: basisReportId, basis_note: note.value || null });
        mm.close(); toast("Pengumuman disiarkan: aplikasi, Telegram, SMS");
      }),
    }, "Siarkan sekarang"), h("button", { class: "sec", onclick: () => mm.close() }, "Batal")));
}

// ---------- peringatan (semua role) ----------
async function viewAlerts(box) {
  const rows = await api("GET", "/alerts?limit=50");
  const isCoord = me.role === "koordinator", isPos = me.role === "pos_pantau";
  box.append(h("h2", {}, "Peringatan"), h("div", { class: "btns no-print", style: "margin-bottom:12px" },
    h("button", { class: "sec small", onclick: reload }, "Segarkan"),
    isPos ? h("button", { class: "danger small", onclick: () => openBroadcastModal() }, "Buat pengumuman (pengamatan langsung)") : null));
  if (!rows.length) box.append(h("div", { class: "notice ok" }, "Belum ada peringatan untuk wilayah Anda."));
  for (const a of rows) {
    const dl = h("div"), extra = h("div");
    const correctable = isPos && !a.internal && ["pengumuman", "sungai", "level", "prediksi"].includes(a.kind);
    box.append(h("div", { class: "card", style: `border-left:6px solid ${LEVEL_COLOR[a.level] || "#cbd5e1"}` },
      h("div", { class: "btns" }, badge(a.kind.toUpperCase()), a.level ? lvl(a.level) : null, a.verification ? verifBadge(a.verification) : null,
        a.internal ? badge("INTERNAL", "b-warn") : null, a.sms ? badge("SMS", "b-info") : null, a.target_roles ? badge("untuk: " + a.target_roles.join(", "), "b-info") : null,
        h("span", { class: "muted small-text" }, `#${a.id}${a.incident_id ? ` · kejadian #${a.incident_id}` : ""} · ${fmt(a.created_at)}`)),
      h("pre", { class: "msg" }, a.message),
      h("div", { class: "btns" },
        isCoord || isPos ? h("button", { class: "sec small", onclick: act(async () => {
          const d = await api("GET", `/alerts/${a.id}/deliveries`);
          dl.replaceChildren(table([{ label: "Kanal", key: "channel" }, { label: "Penerima", key: "recipient" },
            { label: "Status", render: x => badge(x.status.toUpperCase(), x.status === "gagal" ? "b-bad" : "b-ok") }, { label: "Galat", render: x => x.error || "-" }, { label: "Waktu", render: x => fmt(x.created_at) }],
          d, "Belum ada pengiriman: tidak ada penerima dengan chat ID / nomor SMS yang opt-in."));
        }) }, "Status pengiriman (Telegram & SMS)") : null,
        correctable ? h("button", { class: "sec small", onclick: () => {
          const text = h("textarea", { placeholder: "Pesan koreksi (kosongkan bila hanya membatalkan)" }), why = h("input", { placeholder: "Alasan (wajib)" });
          extra.replaceChildren(h("div", { class: "card flat", style: "background:var(--soft)" }, field("Pesan koreksi", text), field("Alasan", why), h("div", { class: "btns" },
            h("button", { class: "small", onclick: act(async () => { if (!text.value.trim()) throw new Error("Isi pesan koreksi"); await api("POST", `/alerts/${a.id}/correct`, { cancel: false, reason: why.value, message: text.value }); await reload(); }, "Koreksi dikirim") }, "Kirim koreksi"),
            h("button", { class: "danger small", onclick: act(async () => { await api("POST", `/alerts/${a.id}/correct`, { cancel: true, reason: why.value }); await reload(); }, "Pembatalan dikirim") }, "Batalkan pengumuman"))));
        } }, "Koreksi / batalkan") : null),
      dl, extra));
  }
}

// ---------- data keluarga (koordinator) ----------
async function viewFamily(box) {
  const residents = await api("GET", "/residents");
  const pick = h("select", {}, residents.map(r => h("option", { value: r.id }, `${r.name}${r.vulnerability.length ? " (rentan)" : ""}`)));
  const list = h("div"), form = h("div");
  const load = async () => {
    if (!pick.value) return;
    const id = pick.value, members = await api("GET", `/residents/${id}/family`);
    const f = { n: h("input"), rel: h("input", { placeholder: "anak, cucu, ayah…" }), age: h("input", { type: "number", min: 0, max: 120 }), ph: h("input"), note: h("textarea", { placeholder: "Catatan evakuasi (alergi, obat, perlu digendong…)" }) };
    const vul = ["balita", "lansia", "disabilitas", "sakit", "hamil", "anak"].map(v => ({ v, c: h("input", { type: "checkbox" }) }));
    list.replaceChildren(h("div", { class: "card" }, h("h3", {}, "Anggota keluarga"),
      h("p", { class: "muted small-text" }, "Data sensitif: pembacaan dicatat di audit log, dan memengaruhi prioritas evakuasi (balita, lansia, sakit)."),
      table([{ label: "Nama", key: "name" }, { label: "Hubungan", render: m => m.relation || "-" }, { label: "Usia", render: m => m.age ?? "-" },
        { label: "Kondisi", render: m => m.vulnerability.join(", ") || "-" }, { label: "Catatan", render: m => m.note || "-" },
        { label: "", render: m => h("button", { class: "danger small", onclick: act(async () => { await api("DELETE", `/residents/${id}/family/${m.id}`); await load(); }, "Anggota dihapus") }, "Hapus") }], members, "Belum ada anggota keluarga tercatat.")));
    form.replaceChildren(h("div", { class: "card" }, h("h3", {}, "Tambah anggota"),
      h("div", { class: "row" }, field("Nama", f.n), field("Hubungan", f.rel), field("Usia", f.age), field("Telepon", f.ph)),
      h("p", { class: "muted small-text", style: "margin:0" }, "Kondisi:"), vul.map(x => h("label", { class: "chk", style: "display:inline-block;margin-right:14px" }, x.c, x.v)),
      field("Catatan", f.note),
      h("button", { onclick: act(async () => { await api("POST", `/residents/${id}/family`, { name: f.n.value, relation: f.rel.value || null, age: num(f.age.value), phone: f.ph.value || null, vulnerability: vul.filter(x => x.c.checked).map(x => x.v), note: f.note.value || null }); await load(); }, "Anggota ditambahkan") }, "Simpan")));
  };
  pick.onchange = load;
  box.append(h("h2", {}, "Data Keluarga"), h("div", { class: "row", style: "max-width:420px" }, field("Kepala keluarga / warga", pick)), list, form);
  await load();
}

// ---------- admin: hanya kelola pengguna + audit hanya-baca ----------
async function viewAdmin(box) {
  const [users, regions, logs] = await Promise.all([api("GET", "/users"), api("GET", "/regions"), api("GET", "/audit-logs?limit=100")]);
  const f = { u: h("input"), n: h("input"), p: h("input", { type: "password" }), tg: h("input"), ph: h("input") };
  const role = h("select", {}, opts(ROLE_NAMES.map(r => [r, ROLE_LABEL[r] || r])));
  const region = h("select", {}, regionOptions(regions, me.region_id));
  box.append(h("h2", {}, "Kelola Pengguna"),
    h("div", { class: "notice" }, "Admin hanya mengelola akun dan membaca audit log. Data operasional dan data pribadi warga tidak dapat diakses dari sini."),
    h("div", { class: "card" }, h("h3", {}, "Akun"), table([
      { label: "Username", key: "username" }, { label: "Nama", key: "name" },
      { label: "Role", render: u => h("select", { onchange: act(async ev => { await api("PATCH", `/users/${u.id}`, { role: ev.target.value }); await reload(); }, "Role diubah") }, opts(ROLE_NAMES.map(r => [r, ROLE_LABEL[r] || r]), u.role)) },
      { label: "Wilayah", render: u => h("select", { onchange: act(async ev => { await api("PATCH", `/users/${u.id}`, { region_id: Number(ev.target.value) }); await reload(); }, "Wilayah diubah") }, regionOptions(regions, u.region_id)) },
      { label: "Aktif", render: u => u.is_active ? badge("AKTIF", "b-ok") : badge("NONAKTIF", "b-bad") },
      { label: "", render: u => h("div", { class: "btns" },
        h("button", { class: "sec small", onclick: act(async () => { const p = prompt("Password baru untuk " + u.username + " (min. 8 karakter):"); if (!p) throw new Error("batal"); await api("POST", `/users/${u.id}/reset-password`, { password: p }); }, "Password direset") }, "Reset sandi"),
        u.is_active && u.id !== me.id ? h("button", { class: "danger small", onclick: act(async () => { const reason = prompt("Alasan menonaktifkan " + u.username + ":"); if (!reason) throw new Error("batal"); await api("POST", `/users/${u.id}/deactivate`, { reason }); await reload(); }) }, "Nonaktifkan") : null) }], users),
      h("details", {}, h("summary", {}, "Buat akun"),
        h("div", { class: "row" }, field("Username (a-z 0-9 _ .)", f.u), field("Nama", f.n), field("Password (min 8)", f.p)),
        h("div", { class: "row" }, field("Role", role), field("Wilayah / pos", region), field("Ponsel", f.ph), field("Telegram chat ID", f.tg)),
        h("button", { onclick: act(async () => { await api("POST", "/users", { username: f.u.value, name: f.n.value, password: f.p.value, role: role.value, region_id: Number(region.value), phone: f.ph.value || null, telegram_chat_id: f.tg.value || null }); await reload(); }, "Akun dibuat") }, "Simpan"))),
    h("div", { class: "card" }, h("h3", {}, "Audit log (hanya-baca, 100 terakhir)"), table([
      { label: "Waktu", render: l => fmt(l.created_at) }, { label: "Pelaku", render: l => l.actor_id ? "user #" + l.actor_id : "sistem" }, { label: "Aksi", key: "action" },
      { label: "Objek", render: l => `${l.entity_type} ${l.entity_id ?? ""}` }, { label: "Alasan", render: l => l.reason || "-" }], logs)));
}

// ---------- pasang ke TABS ----------
Object.assign(TABS, {
  sarmap: { label: "Peta SAR", icon: "sos", render: viewSarMap, refresh: 15000 },
  prediksi: { label: "Prediksi Banjir", icon: "prediksi", render: viewForecast, refresh: 60000 },
  keluarga: { label: "Data Keluarga", icon: "keluarga", render: viewFamily },
  alerts: { label: "Peringatan", icon: "alert", render: viewAlerts },
  admin: { label: "Kelola User", icon: "admin", render: viewAdmin },
});
TABS.reports.label = "Laporan & Verifikasi";
TABS.incidents.label = "Kejadian & Level";
