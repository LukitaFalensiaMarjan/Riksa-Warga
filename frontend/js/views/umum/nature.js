import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { SKY, ago, svgBox } from "../warga/kit.js";

// ---------- Kondisi alam: sungai, hujan, dan perkiraan risiko (semua peran non-admin) ----------
const COND = { normal: ["Normal", "#17a98a"], waspada: ["Waspada", "#d97706"], bahaya: ["Meluap", "#dc2626"], data_kedaluwarsa: ["Data lama", "#64748b"], tidak_ada_data: ["Belum ada data", "#64748b"] };
const RISK = { rendah: ["Rendah", "#17a98a"], sedang: ["Sedang", "#d97706"], tinggi: ["Tinggi", "#dc2626"] };
const TREND = { naik: "↗ naik", turun: "↘ turun", stabil: "→ stabil", belum_cukup_data: "belum cukup data" };
const BTN = [["normal", "Normal", "normal"], ["waspada", "Waspada", "waspada"], ["meluap", "Meluap", "bahaya"]];  // [kirim, label, status pos]

const NS = "http://www.w3.org/2000/svg";
const el = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };

// batang hujan per jam: 12 jam lalu sampai 24 jam ke depan; batang masa depan dibuat lebih pudar
function rainChart(hourly) {
  const W = 360, H = 96, B = 16, n = hourly.length, bw = W / Math.max(n, 1), max = Math.max(5, ...hourly.map(x => x.mm));
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "n-chart", role: "img", "aria-label": "Grafik hujan per jam" });
  const now = Date.now();
  let cut = hourly.findIndex(x => new Date(x.t) > now); if (cut < 0) cut = n;
  hourly.forEach((x, i) => {
    const bh = Math.max(x.mm > 0 ? 2 : 0, (x.mm / max) * (H - B - 6));
    const r = el("rect", { x: i * bw + 1, y: H - B - bh, width: bw - 2, height: bh, rx: 2, fill: x.mm >= 10 ? "#dc2626" : x.mm >= 3 ? "#1e88f0" : "#6cc4ff", opacity: i < cut ? 1 : .55 });
    const t = el("title", {}); t.textContent = `${new Date(x.t).toLocaleTimeString("id-ID", { timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit" })} WIB · ${x.mm} mm · peluang ${x.p}%`;
    r.append(t); svg.append(r);
  });
  svg.append(el("line", { x1: cut * bw, x2: cut * bw, y1: 0, y2: H - B, stroke: "currentColor", "stroke-dasharray": "3 3", opacity: .6 }));
  [["-12 j", 0, "start"], ["sekarang", cut * bw, "middle"], ["+24 j", W, "end"]].forEach(([txt, x, a]) => { const t = el("text", { x, y: H - 3, "text-anchor": a, "font-size": 10, fill: "currentColor", opacity: .75 }); t.textContent = txt; svg.append(t); });
  return svg;
}

function setCondition(s, key, label) {
  const note = h("textarea", { placeholder: "Catatan kondisi daerah (opsional): air keruh, arus deras di jembatan, dll.", style: "min-height:70px" });
  const close = openModal(`Ubah kondisi ${s.name} ke ${label}?`,
    h("p", { class: "muted small-text" }, key === "normal" ? "Status pos dan semua peran akan kembali normal."
      : "Status pos berubah untuk semua peran dan dapat memicu peringatan otomatis. Pastikan sesuai kondisi di lapangan."),
    note,
    h("div", { class: "btns" }, h("button", { class: key === "meluap" ? "danger" : "", onclick: act(async () => { await api("POST", `/stations/${s.id}/condition`, { condition: key, note: note.value.trim() || undefined }); close(); await reload(); }, `Kondisi ${s.name}: ${label}`) }, `Ya, ${label}`),
      h("button", { class: "ghost", onclick: () => close() }, "Batal")));
}

export async function viewNature(box) {
  const d = await api("GET", "/nature");
  const [rl, rc] = RISK[d.overall_risk], canSet = me.role === "pos_pantau";

  const pill = h("div", { class: "d-pill", style: `--lc:${rc}` },
    h("span", { class: "d-pill-ico" }, icon(d.overall_risk === "rendah" ? "check" : "alert")),
    h("span", { class: "d-pill-t" }, h("small", {}, "Perkiraan potensi banjir"), h("b", {}, rl.toUpperCase()),
      h("em", {}, d.overall_risk === "rendah" ? "Belum ada tanda bahaya. Tetap pantau." : "Siapkan diri dan ikuti arahan petugas.")));
  const banner = h("div", { class: "d-banner" }, svgBox("d-sky", SKY),
    h("h1", {}, "Kondisi Alam"), h("p", {}, `Sungai & hujan di ${d.stations.length} pos pantau · diperbarui ${ago(d.generated_at)}`), pill);

  const card = s => {
    const [cl, cc] = COND[s.status] || COND.tidak_ada_data, [rkl, rkc] = RISK[s.risk.level], cm = s.latest?.level_cm;
    const pct = cm != null ? Math.min(100, Math.round(cm / s.danger_cm * 100)) : 0, wpct = Math.round(s.warning_cm / s.danger_cm * 100);
    const stat = (k, v) => h("div", {}, h("b", {}, v), h("span", {}, k));
    return h("div", { class: "card n-card" },
      h("div", { class: "n-head" }, h("div", {}, h("h3", {}, icon("pos"), s.name), h("small", { class: "muted" }, `${s.river_name || "Sungai"}${s.is_upstream ? " · hulu" : ""}`)),
        h("span", { class: "n-cond", style: `--c:${cc}` }, cl)),
      h("div", { class: "n-gauge" }, h("div", { class: "occ" }, h("i", { style: `width:${pct}%;background:${cc}` }), h("u", { style: `left:${wpct}%` })),
        h("small", { class: "muted" }, cm != null ? `${cm} cm · waspada ${s.warning_cm} · meluap ${s.danger_cm} · ${TREND[s.direction]}${s.latest ? ` · ${ago(s.latest.observed_at)}` : ""}` : "Belum ada bacaan")),
      canSet ? h("div", { class: "n-btns", role: "group", "aria-label": `Kondisi sungai ${s.name}` }, BTN.map(([k, lb, st]) =>
        h("button", { type: "button", class: `n-b n-${k}` + (s.status === st ? " on" : ""), "aria-pressed": s.status === st, onclick: () => s.status === st ? null : setCondition(s, k, lb) }, lb))) : null,
      h("div", { class: "n-rain" },
        s.rain ? [h("div", { class: "n-stats" }, stat("hujan 6 j lalu", `${s.rain.past_6h} mm`), stat("6 j ke depan", `${s.rain.next_6h} mm`), stat("24 j ke depan", `${s.rain.next_24h} mm`), stat("peluang hujan", `${s.rain.peak_probability}%`)), rainChart(s.rain.hourly)]
          : h("p", { class: "muted small-text" }, "Data hujan belum tersedia (tidak ada koneksi ke layanan cuaca).")),
      h("div", { class: "n-risk", style: `--c:${rkc}` }, h("b", {}, `Potensi banjir: ${rkl}`), h("ul", {}, s.risk.reasons.map(r => h("li", {}, r)))));
  };

  box.append(banner, h("div", { class: "n-grid" }, d.stations.length ? d.stations.map(card) : h("div", { class: "card w-empty" }, h("h3", {}, "Belum ada pos pantau"), h("p", {}, "Koordinator dapat menambahkan pos pantau."))),
    h("p", { class: "muted small-text", style: "margin-top:12px" }, `Hujan: ${d.rain_source} (per jam, UTC+7). Perkiraan risiko memakai aturan sederhana dari kondisi sungai, tren, dan hujan — bukan prakiraan resmi BMKG. Terakhir dimuat ${fmt(d.generated_at)}.`));
}
