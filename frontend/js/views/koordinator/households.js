import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { badge, field, opts, regionOptions } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Koordinator: data keluarga untuk evakuasi ----------
const AGES = [["dewasa", "Dewasa"], ["lansia", "Lansia"], ["anak", "Anak"], ["balita", "Balita"]];
const NEEDS = [["disabilitas", "Disabilitas"], ["kursi_roda", "Kursi roda"], ["hamil", "Hamil"], ["sakit_kronis", "Sakit kronis"], ["butuh_oksigen", "Butuh oksigen"]];
const NEED_L = Object.fromEntries(NEEDS);

export async function viewHouseholds(box) {
  const [rows, regions, residents] = await Promise.all([api("GET", "/households"), api("GET", "/regions"), api("GET", "/residents")]);
  const rname = Object.fromEntries(regions.map(r => [r.id, r.name]));

  function form(hh) {
    const f = { n: h("input", { value: hh?.name || "", placeholder: "mis. Keluarga Bapak Asep" }), a: h("input", { value: hh?.address_note || "", placeholder: "Gang, nomor rumah, patokan" }),
      p: h("input", { value: hh?.phone || "", inputmode: "tel" }), no: h("textarea", { style: "min-height:60px", placeholder: "Catatan untuk evakuasi (opsional)" }) };
    f.no.value = hh?.notes || "";
    const region = h("select", {}, regionOptions(regions, hh?.region_id ?? me.region_id, ["rt", "rw"]));
    const head = h("select", {}, h("option", { value: "" }, "— tidak dihubungkan —"), residents.map(r => h("option", { value: r.id, selected: r.id === hh?.resident_id }, r.name)));
    const members = h("div", { class: "hh-members" });
    const addRow = (m = { name: "", age_group: "dewasa", needs: [] }) => {
      const name = h("input", { value: m.name, placeholder: "Nama anggota" }), age = h("select", {}, opts(AGES, m.age_group));
      const needs = new Set(m.needs);
      const row = h("div", { class: "hh-row" }, name, age,
        h("div", { class: "hh-needs" }, NEEDS.map(([k, t]) => h("button", { type: "button", class: "w-chip" + (needs.has(k) ? " on" : ""), onclick: ev => { needs.has(k) ? needs.delete(k) : needs.add(k); ev.currentTarget.classList.toggle("on"); } }, t))),
        h("button", { type: "button", class: "ghost small", "aria-label": "Hapus anggota", onclick: () => row.remove() }, "✕"));
      row.get = () => ({ name: name.value.trim(), age_group: age.value, needs: [...needs] });
      members.append(row);
    };
    (hh?.members.length ? hh.members : [undefined]).forEach(m => addRow(m));
    const close = openModal(hh ? `Ubah ${hh.name}` : "Tambah keluarga",
      field("Nama keluarga", f.n), h("div", { class: "row" }, field("Wilayah (RT/RW)", region), field("Telepon", f.p)), field("Alamat / patokan", f.a),
      field("Kepala keluarga terdaftar (opsional)", head),
      h("h4", { style: "margin:10px 0 4px" }, "Anggota keluarga"), members,
      h("button", { type: "button", class: "sec small", onclick: () => addRow() }, "+ Tambah anggota"), field("Catatan", f.no),
      h("div", { class: "btns", style: "margin-top:10px" }, h("button", {
        onclick: act(async () => {
          const body = { name: f.n.value, region_id: Number(region.value), address_note: f.a.value || null, phone: f.p.value || null, notes: f.no.value || null,
            resident_id: head.value ? Number(head.value) : null, members: [...members.children].map(r => r.get()).filter(m => m.name) };
          await (hh ? api("PUT", `/households/${hh.id}`, body) : api("POST", "/households", body));
          close(); await reload();
        }, "Data keluarga disimpan"),
      }, "Simpan"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }
  function remove(hh) {
    const close = openModal(`Hapus ${hh.name}?`, h("p", { class: "muted small-text" }, "Data keluarga dan anggotanya dihapus. Data warga terdaftar tidak ikut terhapus."),
      h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(async () => { await api("DELETE", `/households/${hh.id}`); close(); await reload(); }, "Keluarga dihapus") }, "Hapus"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }

  const prio = rows.reduce((n, x) => n + x.priority_members, 0);
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Data Keluarga"), h("p", {}, "Catat anggota tiap keluarga, terutama lansia, balita, dan yang butuh bantuan khusus. Tim SAR melihat ringkasannya saat menuju warga.")),
    h("div", { class: "w-chips" }, h("span", { class: "w-chip on" }, `${rows.length} keluarga`), h("span", { class: "w-chip" }, `${prio} anggota prioritas`),
      h("button", { type: "button", class: "n-announce", onclick: () => form(null) }, icon("warga"), "Tambah keluarga")),
    h("div", { class: "n-grid" }, rows.length ? rows.map(x => h("div", { class: "card hh" },
      h("div", { class: "n-head" }, h("div", {}, h("h3", {}, icon("warga"), x.name), h("small", { class: "muted" }, `${rname[x.region_id] || "#" + x.region_id}${x.address_note ? " · " + x.address_note : ""}${x.phone ? " · " + x.phone : ""}`)),
        x.priority_members ? badge(`${x.priority_members} prioritas`, "b-bad") : badge("Tanpa prioritas", "b-ok")),
      h("ul", { class: "hh-list" }, x.members.map(m => h("li", {}, h("b", {}, m.name), ` · ${(AGES.find(a => a[0] === m.age_group) || [, m.age_group])[1]}`, m.needs.map(n => badge(NEED_L[n] || n, "b-warn"))))),
      x.notes ? h("div", { class: "rp-note" }, h("b", {}, "Catatan"), x.notes) : null,
      h("div", { class: "btns", style: "margin-top:10px" }, h("button", { class: "sec small", onclick: () => form(x) }, "Ubah"), h("button", { class: "ghost small", onclick: () => remove(x) }, "Hapus"))))
      : h("div", { class: "card w-empty" }, icon("warga"), h("h3", {}, "Belum ada data keluarga"), h("p", {}, "Tambahkan keluarga agar evakuasi lebih terarah."), h("button", { onclick: () => form(null) }, "Tambah keluarga"))));
}
