import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { getPosition } from "../../lib/geo.js";
import { icon } from "../../lib/icons.js";
import { field, opts } from "../../lib/ui.js";
import { me } from "../../state.js";
import { taskCard } from "../umum/taskCard.js";

export async function viewMyTasks(box) {
  const [tasks, shelters] = await Promise.all([api("GET", "/tasks"), api("GET", "/shelters")]);
  let myPos = null;
  try { myPos = (await getPosition(3000)).slice(0, 2); } catch { /* tanpa jarak */ }
  const active = tasks.filter(t => !["selesai", "gagal", "dibatalkan"].includes(t.status));
  const done = tasks.filter(t => !active.includes(t));
  const usable = shelters.filter(s => s.is_verified);
  const stat = (n, t, ic, c) => h("div", { class: "k-stat", style: `background:${c}` }, h("span", { class: "k-ico" }, icon(ic)), h("div", {}, h("b", {}, n), h("small", {}, t)));
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Tugas Saya"), h("p", {}, "Tugas dari koordinator daerah. Terima, berangkat, tangani, lalu buat laporan hasil.")),
    h("div", { class: "k-stats", style: "margin-bottom:16px" }, stat(active.length, "Tugas aktif", "tugas", "linear-gradient(135deg,#b45309,#f5a524)"), stat(done.filter(t => t.status === "selesai").length, "Selesai", "check", "linear-gradient(135deg,#0a7a8a,#17c29a)"),
      h("a", { href: "#bantuan", style: "text-decoration:none" }, stat("Buka", "Peta Bantuan warga", "sos", "linear-gradient(135deg,#a8202f,#ef5a52)"))),
    h("div", { class: "notice" }, "Utamakan keselamatan Anda. Jangan memasuki arus deras atau area berbahaya; ikuti arahan koordinator."),
    h("div", {}, active.length ? active.map(t => taskCard(t, { shelters: usable, myPos })) : h("div", { class: "notice ok" }, "Tidak ada tugas aktif. Anda akan menerima notifikasi saat ditugaskan.")));
  const kind = h("select", {}, opts(["jalan_tertutup", "genangan", "pohon_tumbang", "kabel_listrik", "lainnya"]));
  const note = h("input", { placeholder: "keterangan singkat" });
  box.append(h("div", { class: "card" }, h("h3", {}, "Laporkan hambatan jalan di posisi saya"),
    h("p", { class: "muted small-text" }, "Titik ini dipakai untuk memperingatkan rute evakuasi warga."),
    h("div", { class: "row" }, field("Jenis", kind), field("Keterangan", note),
      h("button", { class: "danger", onclick: act(async () => { const p = await getPosition(); await api("POST", "/road-conditions", { region_id: me.region_id, kind: kind.value, lat: p[0], lng: p[1], note: note.value || null }); note.value = ""; }, "Hambatan jalan dilaporkan") }, "Laporkan"))));
  if (done.length) box.append(h("details", { class: "card" }, h("summary", {}, `Riwayat (${done.length})`), done.map(t => taskCard(t))));
}
