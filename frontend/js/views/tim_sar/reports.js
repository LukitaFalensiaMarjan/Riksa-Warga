import { lab } from "../../config.js";
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { badge, prioBadge } from "../../lib/ui.js";
import { ago } from "../warga/kit.js";
import { taskCard } from "../umum/taskCard.js";

// ---------- Tim SAR: laporan hasil tugas ----------
export async function viewSarReports(box) {
  const [tasks, shelters] = await Promise.all([api("GET", "/tasks"), api("GET", "/shelters")]);
  const sname = Object.fromEntries(shelters.map(s => [s.id, s.name]));
  const pending = tasks.filter(t => t.status === "dalam_penanganan");            // sudah ditangani, laporan belum dibuat
  const done = tasks.filter(t => ["selesai", "gagal"].includes(t.status));
  const ok = done.filter(t => t.status === "selesai"), people = ok.reduce((n, t) => n + (t.people_count || 0), 0);
  const stat = (n, t, ic, c) => h("div", { class: "k-stat", style: `background:${c}` }, h("span", { class: "k-ico" }, icon(ic)), h("div", {}, h("b", {}, n), h("small", {}, t)));

  box.append(h("div", { class: "w-head" }, h("h2", {}, "Laporan Tugas"), h("p", {}, "Setelah menolong, buat laporan hasil: apa yang dilakukan, berapa orang, dan ke shelter mana mereka dibawa.")),
    h("div", { class: "k-stats" }, stat(ok.length, "Tugas selesai", "check", "linear-gradient(135deg,#0a7a8a,#17c29a)"), stat(people, "Orang dibantu", "warga", "linear-gradient(135deg,#0b3a6e,#1e88f0)"),
      stat(pending.length, "Menunggu laporan", "tugas", "linear-gradient(135deg,#b45309,#f5a524)"), stat(done.length - ok.length, "Tidak terlaksana", "kejadian", "linear-gradient(135deg,#a8202f,#ef5a52)")));

  box.append(h("h3", { class: "d-h", style: "margin-top:20px" }, icon("tugas"), "Menunggu laporan hasil"),
    pending.length ? pending.map(t => taskCard(t, { shelters: shelters.filter(s => s.is_verified) }))
      : h("div", { class: "notice ok" }, "Tidak ada tugas yang menunggu laporan. Tugas yang sedang ditangani muncul di sini; tekan Selesai untuk mengisi laporannya."));

  box.append(h("h3", { class: "d-h", style: "margin-top:20px" }, icon("list"), "Riwayat laporan"),
    done.length ? done.map(t => h("div", { class: "card rp", style: `--rc:${t.status === "selesai" ? "#17a98a" : "#dc2626"}` },
      h("div", { class: "rp-top" }, h("div", { class: "grow" }, h("h4", {}, t.resident_name || "Tugas umum", " ", prioBadge(t.priority), " ", badge(lab(t.status), t.status === "selesai" ? "b-ok" : "b-bad")),
        h("div", { class: "muted small-text" }, `#${t.id} · ${t.task_type} · ${ago(t.updated_at)} · ${fmt(t.updated_at)}`))),
      h("p", { class: "rp-desc" }, t.description),
      t.result ? h("div", { class: "rp-note" }, h("b", {}, t.status === "selesai" ? "Laporan hasil" : "Alasan tidak terlaksana"), t.result) : null,
      t.status === "selesai" ? h("div", { class: "btns", style: "margin-top:8px" }, badge(`${t.people_count ?? 0} orang`, "b-info"), t.shelter_id ? badge("Shelter: " + (sname[t.shelter_id] || "#" + t.shelter_id), "b-ok") : badge("Tidak ke shelter")) : null))
      : h("div", { class: "card w-empty" }, icon("list"), h("h3", {}, "Belum ada laporan"), h("p", {}, "Laporan hasil tugas yang sudah Anda buat akan tampil di sini.")));
}
