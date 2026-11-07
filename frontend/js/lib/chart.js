import { h } from "./dom.js";
import { fmt, utc } from "./format.js";

// Grafik tinggi air interaktif: pita zona (aman / waspada / bahaya), garis halus, sorot saat disentuh, garis pratinjau input.
const NS = "http://www.w3.org/2000/svg";
const el = (t, a = {}, txt) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; return e; };
const COND = { normal: "Normal", naik: "Naik", arus_deras: "Arus deras", meluap: "Meluap" };
const hhmm = t => new Date(t).toLocaleTimeString("id-ID", { timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit" }).replace(".", ":");
const dmy = t => new Date(t).toLocaleDateString("id-ID", { timeZone: "Asia/Jakarta", day: "2-digit", month: "short" });

// kurva halus (Catmull-Rom -> Bezier) yang tidak melewati batas atas/bawah titik
function smooth(p) {
  if (p.length < 3) return p.map((q, i) => `${i ? "L" : "M"}${q[0]},${q[1]}`).join(" ");
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
    d += ` C${b[0] + (c[0] - a[0]) / 6},${b[1] + (c[1] - a[1]) / 6} ${c[0] - (e[0] - b[0]) / 6},${c[1] - (e[1] - b[1]) / 6} ${c[0]},${c[1]}`;
  }
  return d;
}

export function chart(readings, station, { hours = 12 } = {}) {
  const W = 640, H = 280, PL = 44, PR = 14, PT = 14, PB = 30;
  const now = Date.now(), t0 = now - hours * 3600e3;
  const pts = readings.map(r => ({ t: Math.max(t0, +utc(r.observed_at)), v: r.level_cm, r })).sort((a, b) => a.t - b.t);
  const max = Math.max(station.danger_cm * 1.25, ...pts.map(p => p.v * 1.12), 10);
  const x = t => PL + ((t - t0) / (now - t0)) * (W - PL - PR), y = v => H - PB - (v / max) * (H - PT - PB);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "ch", role: "img", "aria-label": `Grafik tinggi air ${station.name}` });

  svg.append(el("defs", {}), ...[]);
  const grad = el("linearGradient", { id: "chg" + station.id, x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(el("stop", { offset: "0%", "stop-color": "#1e88f0", "stop-opacity": ".45" }), el("stop", { offset: "100%", "stop-color": "#1e88f0", "stop-opacity": "0" }));
  svg.firstChild.append(grad);

  // zona
  [[0, station.warning_cm, "#17a98a", "Aman"], [station.warning_cm, station.danger_cm, "#d97706", "Waspada"], [station.danger_cm, max, "#dc2626", "Bahaya"]].forEach(([a, b, c, t]) => {
    svg.append(el("rect", { x: PL, y: y(b), width: W - PL - PR, height: y(a) - y(b), fill: c, opacity: .11 }));
    if (y(a) - y(b) > 16) svg.append(el("text", { x: PL + 8, y: y(b) + 14, class: "ch-zone", fill: c }, t));
  });
  // sumbu & garis bantu
  const step = max > 400 ? 100 : max > 200 ? 50 : max > 80 ? 20 : 10;
  for (let v = 0; v <= max; v += step) {
    svg.append(el("line", { x1: PL, x2: W - PR, y1: y(v), y2: y(v), class: "ch-grid" }), el("text", { x: PL - 6, y: y(v) + 4, "text-anchor": "end", class: "ch-txt" }, v));
  }
  for (let i = 0; i <= 4; i++) {
    const t = t0 + (now - t0) * i / 4;
    svg.append(el("text", { x: x(t), y: H - 10, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle", class: "ch-txt" }, hours > 24 ? `${dmy(t)} ${hhmm(t)}` : i === 4 ? "sekarang" : hhmm(t)));
  }
  [[station.warning_cm, "#d97706", "waspada"], [station.danger_cm, "#dc2626", "bahaya"]].forEach(([v, c, t]) => {
    svg.append(el("line", { x1: PL, x2: W - PR, y1: y(v), y2: y(v), stroke: c, "stroke-dasharray": "5 4", "stroke-width": 1.5 }),
      el("text", { x: W - PR - 4, y: y(v) - 5, "text-anchor": "end", class: "ch-lim", fill: c }, `${t} ${v} cm`));
  });

  const wrap = h("div", { class: "ch-wrap" }), tip = h("div", { class: "ch-tip", hidden: true });
  const cross = el("line", { y1: PT, y2: H - PB, class: "ch-cross", opacity: 0 }), dot = el("circle", { r: 7, class: "ch-dot", opacity: 0 });
  const prevLine = el("line", { x1: PL, x2: W - PR, class: "ch-prev", opacity: 0 }), prevTxt = el("text", { x: PL + 6, class: "ch-prevtxt", opacity: 0 });

  if (pts.length) {
    const xy = pts.map(p => [x(p.t), y(p.v)]);
    const line = smooth(xy);
    svg.append(el("path", { d: `${line} L${xy.at(-1)[0]},${H - PB} L${xy[0][0]},${H - PB} Z`, fill: `url(#chg${station.id})`, class: "ch-area" }),
      el("path", { d: line, class: "ch-line", pathLength: 1, fill: "none" }));
    pts.forEach((p, i) => svg.append(el("circle", { cx: xy[i][0], cy: xy[i][1], r: 4, class: "ch-pt" + (p.r.source_mode === "simulation" ? " sim" : "") })));
    // tanda "terakhir"
    const last = pts.at(-1);
    svg.append(el("circle", { cx: x(last.t), cy: y(last.v), r: 7, class: "ch-last" }));
  }
  svg.append(cross, dot, prevLine, prevTxt);

  const hit = el("rect", { x: PL, y: PT, width: W - PL - PR, height: H - PT - PB, fill: "transparent", class: "ch-hit" });
  svg.append(hit);
  const move = ev => {
    if (!pts.length) return;
    const b = svg.getBoundingClientRect(), mx = ((ev.clientX - b.left) / b.width) * W;
    const p = pts.reduce((m, q) => Math.abs(x(q.t) - mx) < Math.abs(x(m.t) - mx) ? q : m);
    cross.setAttribute("x1", x(p.t)); cross.setAttribute("x2", x(p.t)); cross.setAttribute("opacity", 1);
    dot.setAttribute("cx", x(p.t)); dot.setAttribute("cy", y(p.v)); dot.setAttribute("opacity", 1);
    tip.hidden = false;
    tip.replaceChildren(h("b", {}, `${p.v} cm`), h("span", {}, COND[p.r.river_condition] || p.r.river_condition), h("small", {}, `${fmt(p.r.observed_at)}${p.r.source_mode === "simulation" ? " · SIMULASI" : ""}`), p.r.note ? h("small", {}, p.r.note) : null);
    const left = (x(p.t) / W) * b.width;
    tip.style.left = Math.min(Math.max(left, 70), b.width - 70) + "px"; tip.style.top = Math.max(4, (y(p.v) / H) * b.height - 70) + "px";
  };
  const leave = () => { cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); tip.hidden = true; };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move); svg.addEventListener("pointerleave", leave);

  wrap.append(svg, tip);
  // garis putus-putus biru: nilai yang sedang diketik/digeser pada form input
  wrap.setPreview = v => {
    const on = v != null && v !== "" && !Number.isNaN(+v);
    const yy = y(Math.min(+v, max));
    [prevLine, prevTxt].forEach(n => n.setAttribute("opacity", on ? 1 : 0));
    prevLine.setAttribute("y1", yy); prevLine.setAttribute("y2", yy); prevTxt.setAttribute("y", yy - 5); prevTxt.textContent = on ? `pratinjau ${v} cm` : "";
  };
  return wrap;
}

// tangki vertikal: isi naik-turun dengan animasi, tanda ambang, dan bayangan nilai pratinjau
export function gauge(station) {
  const max = station.danger_cm * 1.25, pct = v => Math.max(0, Math.min(100, v / max * 100));
  const fill = h("div", { class: "g-fill" }), ghost = h("div", { class: "g-ghost" }), val = h("b", {}, "—"), sub = h("small", {}, "belum ada data");
  const tank = h("div", { class: "g-tank" }, h("div", { class: "g-zone g-bahaya", style: `bottom:${pct(station.danger_cm)}%` }), h("div", { class: "g-zone g-waspada", style: `bottom:${pct(station.warning_cm)}%;height:${pct(station.danger_cm) - pct(station.warning_cm)}%` }),
    fill, ghost, h("span", { class: "g-mark", style: `bottom:${pct(station.danger_cm)}%` }, `bahaya ${station.danger_cm}`), h("span", { class: "g-mark w", style: `bottom:${pct(station.warning_cm)}%` }, `waspada ${station.warning_cm}`));
  const el_ = h("div", { class: "g" }, tank, h("div", { class: "g-val" }, val, sub));
  el_.set = (v, status) => {
    fill.style.height = v == null ? "0%" : pct(v) + "%";
    fill.dataset.s = status || ""; val.textContent = v == null ? "—" : `${v} cm`;
    sub.textContent = { normal: "Normal", waspada: "Waspada", bahaya: "Meluap", data_kedaluwarsa: "Data lama", tidak_ada_data: "belum ada data" }[status] || "";
  };
  el_.preview = v => { const on = v != null && v !== "" && !Number.isNaN(+v); ghost.style.opacity = on ? 1 : 0; if (on) ghost.style.bottom = pct(+v) + "%"; };
  return el_;
}
