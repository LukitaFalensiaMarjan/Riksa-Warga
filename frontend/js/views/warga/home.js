import { LEVEL_RANK, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { h, toast } from "../../lib/dom.js";
import { fmtDist } from "../../lib/format.js";
import { bearing, compass, dist, getPosition, gmaps } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { postOrQueue } from "../../lib/offline.js";
import { store } from "../../lib/store.js";
import { startTracking, stopTracking } from "../../lib/tracker.js";
import { field } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { LEVEL_TEXT, LV_COLOR, SKY, ago, svgBox } from "./kit.js";

// ---------- Beranda (warga) ----------
export function activeAlerts(alerts) {
  const latest = new Map();
  alerts.filter(a => !a.internal && a.incident_id).forEach(a => { if (!latest.has(a.incident_id)) latest.set(a.incident_id, a); });
  return [...latest.values()].filter(a => ["level", "koreksi"].includes(a.kind))
    .sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level]);
}
export const actionLine = msg => (msg.split("\n").find(l => l.startsWith("Tindakan:")) || "").replace("Tindakan: ", "");

const STATUS_VIEW = {
  belum_terkonfirmasi: ["wait", "sos", "Belum ada kabar dari Anda. Saat bencana, yang belum memberi kabar dianggap butuh bantuan. Tekan SAYA AMAN bila selamat."],
  aman_mandiri: ["ok", "check", "Tercatat dari laporan Anda. Petugas belum memverifikasi di lapangan."],
  aman_terverifikasi: ["ok", "check", "Petugas sudah memastikan Anda aman."],
  butuh_bantuan: ["help", "sos", "Permintaan Anda sudah masuk antrean koordinator. Tetap di tempat aman bila bisa."],
  dalam_penanganan: ["help", "tugas", "Bantuan sedang menuju atau menangani Anda."],
  dalam_perjalanan: ["wait", "rute", "Anda tercatat sedang menuju titik aman."],
  tiba_di_titik_aman: ["ok", "shelter", "Anda tercatat sudah tiba di titik aman."],
};
const NEEDS = [["evakuasi", "rute", "Evakuasi", "Perlu dijemput / dibantu pindah"], ["medis", "medis", "Medis", "Sakit, luka, lansia, ibu hamil"],
  ["logistik", "logistik", "Makanan / air", "Kebutuhan dasar mendesak"], ["lainnya", "more", "Lainnya", "Jelaskan di keterangan"]];
const KIT = ["Dokumen penting (KTP, KK) di plastik", "Senter + baterai cadangan", "Air minum & makanan siap saji", "Obat pribadi & P3K", "Power bank terisi penuh", "Pakaian ganti & selimut", "Peluit & radio kecil", "Uang tunai secukupnya"];


// jalur status keselamatan: indeks langkah aktif per status
const TRACK = ["Kabar masuk", "Ditangani", "Menuju aman", "Di titik aman"];
const TRACK_AT = { aman_mandiri: 1, aman_terverifikasi: 1, butuh_bantuan: 1, dalam_penanganan: 2, dalam_perjalanan: 3, tiba_di_titik_aman: 4 };

const HOUSE = '<svg viewBox="0 0 220 130"><ellipse cx="110" cy="118" rx="104" ry="12" fill="#17c29a" opacity=".25"/><path d="M10 118q60-30 120-8t80 8z" fill="#17c29a" opacity=".35"/><rect x="62" y="56" width="84" height="58" rx="3" fill="#e8f3ff"/><path d="M52 60l62-44 62 44z" fill="#0a5fb0"/><rect x="100" y="80" width="22" height="34" rx="3" fill="#0b3a6e"/><rect x="74" y="68" width="18" height="16" rx="2" fill="#ffd27a"/><circle cx="170" cy="78" r="26" fill="#17c29a"/><path d="M159 78l8 8 15-17" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><g fill="#9bdcff"><circle cx="24" cy="24" r="2"/><circle cx="196" cy="20" r="2"/><circle cx="40" cy="52" r="1.5"/></g></svg>';
const dtWIB = () => new Date().toLocaleString("id-ID", { timeZone: "Asia/Jakarta", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(".", ":");

export async function viewHome(box) {
  const [alerts, res, shelters] = await Promise.all([api("GET", "/alerts?limit=50"), api("GET", "/me/resident"), api("GET", "/shelters")]);
  const live = activeAlerts(alerts), a0 = live[0], lv = a0?.level, sim = a0?.message.startsWith("[SIMULASI]");
  const from = res.last_lat != null ? [res.last_lat, res.last_lng] : res.home_lat != null ? [res.home_lat, res.home_lng] : null;
  const usable = shelters.filter(s => s.is_verified && ["tersedia", "terbatas"].includes(s.status));
  const near = from ? usable.map(s => ({ s, d: dist(from, [s.lat, s.lng]) })).sort((a, b) => a.d - b.d)[0] : usable[0] && { s: usable[0], d: null };
  const first = (me?.name || "Warga").split(" ")[0];

  // ---- 1. sapaan + kondisi wilayah ----
  const pill = h("a", { class: "d-pill" + (a0 ? " l-" + lv : ""), href: "#alerts", style: a0 ? `--lc:${LV_COLOR[lv]}` : "" },
    h("span", { class: "d-pill-ico" }, icon(a0 ? "alert" : "check")),
    h("span", { class: "d-pill-t" }, h("small", {}, a0 ? `${sim ? "SIMULASI · " : ""}Kondisi wilayah · ${ago(a0.created_at)}` : "Kondisi wilayah Anda"),
      h("b", {}, a0 ? `Status ${lv.toUpperCase()}` : "Aman, tidak ada peringatan"),
      a0 ? h("em", {}, actionLine(a0.message) || LEVEL_TEXT[lv]) : null),
    icon("arrow"));
  const banner = h("div", { class: "d-banner" }, svgBox("d-sky", SKY),
    h("div", { class: "d-sys" }, h("span", { class: "d-dot" + (navigator.onLine ? "" : " off") }), h("span", {}, h("small", {}, "Status sistem"), h("b", {}, navigator.onLine ? "Terhubung" : "Offline"))),
    h("h1", {}, `Halo, ${first}! 👋`), h("p", {}, "Bersama kita lebih siap menghadapi bencana"), pill);

  // ---- 2. tombol aksi ----
  const help = h("div", { class: "card help-pop", hidden: true });
  const sendStatus = async (body, share) => {
    if (share) { try { const p = await getPosition(7000); body.lat = p[0]; body.lng = p[1]; } catch (e) { toast(e.message + " — status tetap dikirim tanpa lokasi", true); } }
    const r = await postOrQueue("/me/status", body, body.status === "aman" ? "Saya Aman" : "Butuh Bantuan");
    if (r.sent) { toast(body.status === "aman" ? "Terima kasih, status aman terkirim" : "Permintaan bantuan terkirim ke koordinator"); await reload(); }
  };
  let need = "evakuasi";
  const shareLoc = h("input", { type: "checkbox", checked: true });
  const note = h("textarea", { placeholder: "Contoh: ada lansia di rumah, air sudah selutut" });
  const needBtns = NEEDS.map(([v, ic, t, d]) => h("button", { type: "button", class: v === need ? "on" : "", onclick: ev => { need = v; needBtns.forEach(b => b.classList.toggle("on", b === ev.currentTarget)); } }, icon(ic), h("b", {}, t), h("small", {}, d)));
  help.append(h("h3", {}, "Apa yang Anda butuhkan?"), h("div", { class: "need-grid" }, needBtns), field("Keterangan (opsional)", note),
    h("label", { class: "chk" }, shareLoc, "Bagikan lokasi saya (hanya Koordinator & Tim SAR yang ditugaskan)"),
    h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(() => sendStatus({ status: "butuh_bantuan", need_type: need, note: note.value.trim() || null }, shareLoc.checked)) }, "Kirim permintaan bantuan"),
      h("button", { class: "ghost", onclick: () => { help.hidden = true; } }, "Batal")));
  const openHelp = () => { help.hidden = false; help.scrollIntoView({ behavior: "smooth", block: "center" }); };
  const isSafe = res.latest_status?.startsWith("aman") || res.latest_status === "tiba_di_titik_aman";
  const go = h("span", { class: "d-go" }, icon("arrow"));
  const aSafe = h("button", { class: "d-act d-safe" + (isSafe ? " done" : ""), onclick: act(async ev => { const b = ev.currentTarget; b.classList.add("sending"); await sendStatus({ status: "aman" }, false); b.classList.remove("sending"); }) },
    h("span", { class: "d-big-ico" }, icon("check")), h("span", { class: "d-act-t" }, h("b", {}, "Saya aman"), h("small", {}, isSafe ? `Terkirim ${ago(res.latest_status_at)}` : "Kabari keluarga & koordinator bahwa Anda selamat")), go.cloneNode(true));
  const aHelp = h("button", { class: "d-act d-help", onclick: openHelp }, h("span", { class: "d-mid-ico" }, icon("sos")), h("span", { class: "d-act-t" }, h("b", {}, "Butuh bantuan"), h("small", {}, "Evakuasi, medis, logistik")), go.cloneNode(true));
  const aRep = h("button", { class: "d-act d-rep", onclick: () => { location.hash = "#lapor"; } }, h("span", { class: "d-mid-ico" }, icon("lapor")), h("span", { class: "d-act-t" }, h("b", {}, "Lapor kejadian"), h("small", {}, "Air naik atau banjir")), go.cloneNode(true));
  const hint = h("div", { class: "d-hint" }, h("span", { class: "d-hint-ico" }, icon("sos")),
    h("span", {}, h("b", {}, "Saat darurat, tekan salah satu tombol di bawah"), h("small", {}, "Kabari bahwa Anda selamat, minta bantuan, atau laporkan kejadian di sekitar Anda.")),
    h("span", { class: "d-hint-arr" }, icon("arrow")));
  const acts = h("div", {}, hint, h("div", { class: "d-acts" }, aSafe, aHelp, aRep), help);

  // ---- 3. strip update ----
  const strip = h("div", { class: "d-strip" }, h("span", { class: "d-pulse" }, icon("pos")), h("span", {}, `Update terakhir: ${dtWIB()} WIB`),
    h("a", { class: "d-link", href: "#peta" }, icon("peta"), "Lihat peta lengkap", icon("arrow")));

  // ---- 4. status keselamatan ----
  const [sk, , sexp] = STATUS_VIEW[res.latest_status] || ["wait", "sos", ""];
  const at = TRACK_AT[res.latest_status] || 0, helpPath = ["butuh_bantuan", "dalam_penanganan"].includes(res.latest_status);
  // Lokasi siaga: izin diberikan sekali, lalu posisi dikirim otomatis selama aplikasi terbuka. Bisa dicabut kapan saja.
  const tracking = !!res.consent;
  const enable = () => {
    const close = openModal("Aktifkan lokasi siaga?",
      h("p", {}, "Izin ini cukup diberikan sekali. Selama aplikasi terbuka, posisi Anda diperbarui otomatis agar petugas bisa menemukan Anda bila terjadi bencana."),
      h("ul", { class: "small-text muted", style: "padding-left:18px" },
        h("li", {}, "Hanya terlihat oleh Koordinator wilayah Anda dan Tim SAR yang ditugaskan."),
        h("li", {}, "Tidak berjalan saat aplikasi ditutup."), h("li", {}, "Dapat dimatikan kapan saja; lokasi terakhir ikut dihapus.")),
      h("div", { class: "btns" }, h("button", { onclick: act(async () => {
        const p = await getPosition();                     // memunculkan izin lokasi peramban
        await api("POST", "/me/location-consent", { granted: true });
        await api("POST", "/me/location", { lat: p[0], lng: p[1], kind: "auto" });
        startTracking(); close(); toast("Lokasi siaga aktif"); await reload();
      }) }, "Izinkan"), h("button", { class: "ghost", onclick: () => close() }, "Nanti")));
  };
  const disable = () => {
    const close = openModal("Matikan lokasi siaga?", h("p", {}, "Lokasi terakhir Anda dihapus dan tidak lagi dibagikan. Saat bencana petugas akan sulit menemukan Anda."),
      h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(async () => {
        await api("POST", "/me/location-consent", { granted: false }); stopTracking(); close(); await reload();
      }, "Lokasi siaga dimatikan") }, "Matikan"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  };
  const stat = h("div", { class: "card d-stat" }, h("h3", {}, icon("pin"), "Status keselamatan saya"),
    h("div", { class: "d-stat-body" },
      h("div", { class: "d-stat-t" },
        h("div", { class: "d-ring " + sk }, icon(sk === "help" ? "sos" : sk === "wait" ? "clock" : "check")),
        h("div", {}, h("b", {}, lab(res.latest_status)), h("p", {}, sexp || "Tekan SAYA AMAN bila Anda selamat."), h("small", {}, res.latest_status_at ? ago(res.latest_status_at) : ""))),
      svgBox("d-house", HOUSE)),
    h("div", { class: "strack" + (helpPath ? " red" : "") }, TRACK.map((t, i) => h("div", { class: i < at ? "on" : "" }, h("i", {}, i < at ? icon("check") : i + 1), h("span", {}, t)))),
    h("div", { class: "btns", style: "margin-top:12px" }, h("button", { class: "sec small", onclick: openHelp }, icon("more"), "Ubah status"),
      tracking ? h("div", { class: "track-on" }, h("span", { class: "d-dot" }), `Lokasi siaga aktif${res.last_location_at ? " · " + ago(res.last_location_at) : ""}`, h("button", { class: "ghost small", onclick: disable }, "Matikan"))
      : h("button", { class: "sec small", onclick: enable }, icon("gps"), "Aktifkan lokasi siaga")));

  // ---- 5. informasi terkini ----
  const feed = alerts.filter(a => !a.internal).slice(0, 4);
  const info = h("div", { class: "card d-info" }, h("div", { class: "d-info-h" }, h("h3", {}, icon("alert"), "Informasi terkini"), h("a", { class: "d-link", href: "#alerts" }, "Lihat semua", icon("arrow"))),
    feed.length ? feed.map(a => h("a", { class: "d-feed", href: "#alerts", style: `--lc:${LV_COLOR[a.level] || "#9aa9bd"}` },
      h("span", { class: "d-feed-ico" }, icon(a.level === "evakuasi" || a.level === "siaga" ? "kejadian" : "alert")),
      h("span", { class: "d-feed-t" }, h("b", {}, a.level ? `${a.level[0].toUpperCase()}${a.level.slice(1)}${a.incident_id ? " · kejadian #" + a.incident_id : ""}` : a.kind), h("small", {}, actionLine(a.message) || a.message.split("\n")[0].replace(/^\[SIMULASI\]\s*/, ""))),
      h("span", { class: "d-feed-time" }, ago(a.created_at), h("i"))))
      : h("p", { class: "muted", style: "padding:14px 0 4px" }, "Belum ada informasi untuk wilayah Anda."));

  // ---- 6. titik aman terdekat ----
  let shel;
  if (near) {
    const { s, d } = near, left = s.capacity != null ? Math.max(0, s.capacity - (s.occupancy || 0)) : null, pct = s.capacity ? Math.min(100, Math.round((s.occupancy || 0) / s.capacity * 100)) : 0;
    const brg = from ? bearing(from, [s.lat, s.lng]) : null, bar = h("i"); setTimeout(() => { bar.style.width = pct + "%"; }, 80);
    const fact = (k, v) => h("div", {}, h("b", {}, v), h("span", {}, k));
    shel = h("div", { class: "card" }, h("h3", {}, icon("shelter"), "Titik aman terdekat"),
      h("div", { class: "near" },
        h("div", { class: "compass", title: brg != null ? `Arah ${compass(brg)}` : "" }, h("span", {}, "U"), brg != null ? h("div", { style: `transform:rotate(${brg}deg);display:grid` }, icon("arrow")) : icon("shelter")),
        h("div", {}, h("h4", {}, s.name), h("div", { class: "muted small-text" }, s.address), h("span", { class: "badge b-ok", style: "margin-top:6px" }, lab(s.status)))),
      h("div", { class: "facts" }, fact("jarak lurus", d != null ? fmtDist(d) : "-"), fact("arah", brg != null ? compass(brg) : "-"), fact("tempat sisa", left ?? "?")),
      h("div", { class: "occ" + (pct > 85 ? " full" : pct > 60 ? " mid" : "") }, bar),
      h("div", { class: "muted small-text" }, `Terisi ${s.occupancy || 0} dari ${s.capacity ?? "?"} orang`),
      h("div", { class: "btns", style: "margin-top:12px" }, h("button", { onclick: () => { location.hash = "#peta"; } }, icon("rute"), "Lihat rute di peta"),
        h("a", { href: gmaps(s.lat, s.lng), target: "_blank", rel: "noopener" }, h("button", { class: "sec", type: "button" }, "Google Maps"))));
  } else shel = h("div", { class: "card" }, h("h3", {}, icon("shelter"), "Titik aman terdekat"), h("p", { class: "muted" }, "Belum ada shelter terverifikasi di wilayah Anda."));

  // ---- 7. tas siaga ----
  const KEY = "rw_kit", done = new Set(store.get(KEY, []));
  const pc = h("b"), ring = h("div", { class: "ring" }, pc), cap = h("div", { class: "muted small-text" });
  const upd = () => { const p = Math.round(done.size / KIT.length * 100); ring.style.setProperty("--p", p); pc.textContent = p + "%"; cap.textContent = done.size === KIT.length ? "Tas siaga lengkap. Simpan dekat pintu." : `${KIT.length - done.size} barang lagi untuk lengkap.`; };
  const items = KIT.map(t => h("button", { type: "button", class: "prep-item" + (done.has(t) ? " on" : ""), onclick: ev => { done.has(t) ? done.delete(t) : done.add(t); ev.currentTarget.classList.toggle("on"); store.set(KEY, [...done]); upd(); } }, t));
  upd();
  const kit = h("div", { class: "card" }, h("div", { class: "prep" }, ring, h("div", {}, h("h3", { style: "margin:0" }, "Siapkan tas siaga"), cap)), h("div", { class: "prep-list" }, items));

  // ---- 8. akses cepat + ajakan bagikan lokasi ----
  const quick = [["lapor", "Lapor Kejadian", "Laporkan bencana atau kejadian darurat", "lapor"], ["peta", "Peta Evakuasi", "Lihat rute & titik aman", "peta"], ["list", "Laporan Saya", "Pantau status laporan Anda", "mine"], ["alert", "Peringatan", "Informasi penting terbaru", "alerts"]];
  const tiles = quick.map(([ic, t, d, hash]) => h("a", { class: "d-quick", href: "#" + hash }, h("span", { class: "d-quick-ico" }, icon(ic)), h("span", {}, h("b", {}, t), h("small", {}, d)),
    hash === "alerts" && live.length ? h("em", {}, live.length) : null, icon("arrow")));
  const cta = h("button", { class: "d-cta", onclick: tracking ? () => toast("Lokasi siaga sudah aktif") : enable }, svgBox("d-cta-art", '<svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="50" fill="#fff" opacity=".1"/><circle cx="60" cy="60" r="32" fill="#fff" opacity=".12"/><path d="M60 24c-14 0-24 10-24 24 0 18 24 42 24 42s24-24 24-42c0-14-10-24-24-24zm0 32a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="#fff"/></svg>'),
    h("span", {}, h("b", {}, tracking ? "Lokasi siaga aktif" : "Tetap terhubung"), h("small", {}, tracking ? "Petugas dapat menemukan Anda bila terjadi bencana" : "Aktifkan lokasi siaga sekali saja agar petugas dapat menemukan Anda")), icon("arrow"));

  box.append(h("div", { class: "d-home" }, banner, acts, strip,
    h("div", { class: "d-row2" }, stat, info), h("div", { class: "d-row2 even" }, shel, kit),
    h("div", { class: "d-bottom" }, h("div", {}, h("h3", { class: "d-h" }, icon("sos"), "Akses cepat"), h("div", { class: "d-quicks" }, tiles)), cta)));
  box.querySelectorAll(".d-home > *").forEach((el, i) => { el.classList.add("rise"); el.style.setProperty("--i", i); });
}
