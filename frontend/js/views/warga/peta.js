import { h } from "../../lib/dom.js";
import { viewMapNav } from "../umum/mapnav.js";

// Peta evakuasi (warga): panduan 3 langkah di atas peta & rute yang sama dengan peran lain.
export async function viewWargaMap(box, ctx) {
  await viewMapNav(box, ctx);
  box.firstElementChild?.remove();  // judul bawaan diganti
  box.prepend(
    h("div", { class: "w-head" }, h("h2", {}, "Peta Evakuasi"), h("p", {}, "Cari jalan tercepat ke titik aman, lalu ikuti panah petunjuk.")),
    h("div", { class: "how" },
      h("div", {}, h("b", {}, 1), "Tentukan posisi: pakai GPS atau ketuk peta"),
      h("div", {}, h("b", {}, 2), "Tekan “Cari rute terdekat” lalu pilih shelter"),
      h("div", {}, h("b", {}, 3), "Tekan “Mulai navigasi” dan ikuti panah")));
}
