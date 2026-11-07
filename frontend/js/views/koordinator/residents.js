import { openModal } from "../../lib/modal.js";
import { LABEL, lab } from "../../config.js";
import { act, api } from "../../lib/api.js";
import { $, h, toast } from "../../lib/dom.js";
import { fmt, num } from "../../lib/format.js";
import { dotIcon, newMap } from "../../lib/map.js";
import { badge, field, opts, regionOptions, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Warga (koordinator) ----------
export async function viewResidents(box, ctx) {
  const [sum, queue, regions] = await Promise.all([api("GET", "/residents/summary"), api("GET", "/help-requests"), api("GET", "/regions")]);
  const q = h("input", { placeholder: "cari nama" });
  const vul = h("select", {}, opts([["", "Semua"], ["true", "Hanya rentan"], ["false", "Non-rentan"]]));
  const stf = h("select", {}, opts([["", "Semua status"], ...["belum_terkonfirmasi", "aman_mandiri", "aman_terverifikasi", "butuh_bantuan", "dalam_penanganan", "dalam_perjalanan", "tiba_di_titik_aman", "tidak_dapat_dihubungi"].map(k => [k, LABEL[k]])]));
  const list = h("div"), detail = h("div");
  const load = async () => {
    const qs = new URLSearchParams();
    if (q.value) qs.set("q", q.value); if (vul.value) qs.set("vulnerable", vul.value); if (stf.value) qs.set("status", stf.value);
    const rows = await api("GET", "/residents?" + qs);
    list.replaceChildren(table([
      { label: "Nama", render: r => [h("b", {}, r.name), r.has_smartphone ? "" : " ", r.has_smartphone ? null : badge("tanpa HP", "b-warn")] },
      { label: "Rentan", render: r => r.vulnerability.length ? r.vulnerability.join(", ") : "-" },
      { label: "Status", render: r => [h("b", {}, lab(r.latest_status)), r.latest_status_source ? h("div", { class: "muted small-text" }, `${r.latest_status_source} · ${fmt(r.latest_status_at)}`) : null] },
      { label: "Lokasi", render: r => r.last_lat != null ? "terkini " + fmt(r.last_location_at) : r.home_lat != null ? "rumah" : "-" },
      { label: "", render: r => h("button", { class: "small no-print", onclick: act(() => open(r.id)) }, "Detail") }], rows));
  };
  const open = async id => {
    const [r, hist] = await Promise.all([api("GET", `/residents/${id}`), api("GET", `/residents/${id}/statuses`)]);
    const status = h("select", {}, opts(["butuh_bantuan", "dalam_penanganan", "dalam_perjalanan", "tiba_di_titik_aman", "aman_terverifikasi", "tidak_dapat_dihubungi", "belum_terkonfirmasi"]));
    const source = h("select", {}, opts(["koordinator", "buddy", "keluarga", "petugas"]));
    const need = h("select", {}, opts(["evakuasi", "medis", "logistik", "lainnya"]));
    const note = h("input", { placeholder: "Catatan / metode verifikasi / upaya kontak" });
    detail.replaceChildren(h("div", { class: "card accent" },
      h("h3", {}, r.name, " ", badge(lab(r.latest_status), "b-info")),
      h("p", { class: "muted small-text" }, "Detail sensitif ini dicatat di audit log setiap dibuka."),
      h("p", {}, `Rentan: ${r.vulnerability.join(", ") || "-"} · Smartphone: ${r.has_smartphone ? "ya" : "tidak"} · Consent: ${r.consent ? "ya" : "tidak"}`),
      h("p", {}, "Catatan bantuan: ", r.assistance_notes || "-"), h("p", {}, `Pendamping: ${r.buddy_name || "-"} ${r.buddy_phone || ""}`),
      h("h3", {}, "Catat status (termasuk warga tanpa smartphone)"),
      h("div", { class: "row" }, field("Status", status), field("Sumber", source), field("Jenis bantuan", need)),
      field("Catatan", note),
      h("button", {
        onclick: act(async () => {
          await api("POST", `/residents/${id}/status`, { status: status.value, source: source.value, need_type: status.value === "butuh_bantuan" ? need.value : null, note: note.value || null });
          await open(id); await load();
        }, "Status dicatat"),
      }, "Simpan status"),
      h("h3", { style: "margin-top:14px" }, "Riwayat status"), table([
        { label: "Waktu", render: x => fmt(x.created_at) }, { label: "Status", render: x => lab(x.status) },
        { label: "Sumber", key: "source" }, { label: "Oleh", render: x => "user #" + x.updated_by }, { label: "Catatan", render: x => x.note || "-" }], hist)));
    detail.scrollIntoView({ behavior: "smooth" });
  };
  [q, vul, stf].forEach(el => el.addEventListener("change", load));
  q.addEventListener("input", () => { clearTimeout(q._t); q._t = setTimeout(load, 300); });
  async function askSar() {
    const team = (await api("GET", "/users").catch(() => [])).filter(u => u.role === "tim_sar" && u.is_active);
    const limit = h("select", {}, [3, 5, 10, 20].map(n => h("option", { value: n, selected: n === 5 }, `${n} teratas`)));
    const who = h("select", {}, h("option", { value: "" }, "Belum ditugaskan (atur di menu Tugas)"), team.map(u => h("option", { value: u.id }, u.name)));
    const close = openModal("Ajukan bantuan Tim SAR",
      h("p", { class: "muted small-text" }, "Membuat tugas untuk warga di antrean paling atas (rentan didahulukan). Warga yang sudah punya tugas aktif dilewati."),
      field("Jumlah warga", limit), field("Tugaskan ke", who),
      h("div", { class: "btns" }, h("button", { onclick: act(async () => {
        const t = await api("POST", "/tasks/from-queue", { limit: Number(limit.value), assignee_id: who.value ? Number(who.value) : null });
        close(); toast(t.length ? `${t.length} tugas dibuat` : "Semua warga di antrean sudah punya tugas"); await reload();
      }) }, "Buat tugas"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }
  box.append(h("h2", {}, "Data Warga & Status Keselamatan"),
    h("div", { class: "grid" }, Object.entries(sum.by_status).map(([k, n]) => h("div", { class: "stat", style: `--c:${k === "butuh_bantuan" ? "#dc2626" : k.startsWith("aman") || k === "tiba_di_titik_aman" ? "#0f9d6b" : "#64748b"}` }, h("b", {}, n), h("span", {}, lab(k))))),
    h("div", { class: "card" }, h("h3", {}, "Antrean butuh bantuan (rentan didahulukan; yang belum memberi kabar saat kejadian dianggap butuh bantuan)"),
      queue.length ? h("button", { class: "small no-print", style: "margin-bottom:10px", onclick: askSar }, "Ajukan bantuan Tim SAR untuk antrean teratas") : null, table([
      { label: "Warga", render: x => x.resident.name }, { label: "Rentan", render: x => x.is_vulnerable ? badge("RENTAN", "b-bad") : "-" },
      { label: "Kebutuhan", render: x => x.unconfirmed ? badge("BELUM ADA KABAR", "b-warn") : (x.need_type || "-") }, { label: "Sumber", render: x => x.source || "dianggap otomatis" }, { label: "Sejak", render: x => fmt(x.requested_at) },
      { label: "", render: x => h("button", { class: "small no-print", onclick: act(() => open(x.resident.id)) }, "Tangani") }], queue, "Tidak ada permintaan bantuan.")),
    h("div", { class: "card" }, h("div", { class: "row no-print" }, field("Cari", q), field("Kerentanan", vul), field("Status", stf), h("button", { class: "sec", onclick: () => window.print() }, "Cetak daftar")), list),
    detail);
  await load();
  const f = { name: h("input"), phone: h("input"), notes: h("textarea"), buddy: h("input"), buddyPhone: h("input"), consent: h("input", { type: "checkbox" }), smart: h("input", { type: "checkbox", checked: true }),
    lat: h("input", { type: "number", step: "any" }), lng: h("input", { type: "number", step: "any" }) };
  const region = h("select", {}, regionOptions(regions, me.region_id, ["rt", "rw"]));
  const vulBox = ["lansia", "disabilitas", "anak", "sakit", "hamil", "tinggal_sendiri", "lainnya"].map(v => ({ v, c: h("input", { type: "checkbox" }) }));
  box.append(h("details", { class: "card no-print" }, h("summary", {}, "Tambah data warga"),
    h("div", { class: "row" }, field("Nama", f.name), field("Wilayah (RT/RW)", region), field("Telepon", f.phone)),
    h("label", { class: "chk" }, f.smart, "Memiliki smartphone"),
    h("p", { class: "muted small-text", style: "margin-bottom:0" }, "Kerentanan:"), vulBox.map(x => h("label", { class: "chk", style: "display:inline-block;margin-right:14px" }, x.c, x.v.replaceAll("_", " "))),
    field("Catatan bantuan (sensitif)", f.notes), h("div", { class: "row" }, field("Pendamping (buddy)", f.buddy), field("Telepon pendamping", f.buddyPhone)),
    h("p", { class: "muted small-text" }, "Lokasi rumah — ketuk peta:"), h("div", { id: "resmap", class: "map", style: "height:240px" }), h("div", { class: "row" }, field("Lat rumah", f.lat), field("Lng rumah", f.lng)),
    h("label", { class: "chk" }, f.consent, "Warga/keluarga menyetujui data kerentanan & lokasi disimpan (wajib bila ada data kerentanan)"),
    h("button", {
      onclick: act(async () => {
        await api("POST", "/residents", { name: f.name.value, region_id: Number(region.value), phone: f.phone.value || null, has_smartphone: f.smart.checked, vulnerability: vulBox.filter(x => x.c.checked).map(x => x.v), assistance_notes: f.notes.value || null, buddy_name: f.buddy.value || null, buddy_phone: f.buddyPhone.value || null, consent: f.consent.checked, home_lat: num(f.lat.value), home_lng: num(f.lng.value) });
        await reload();
      }, "Data warga disimpan"),
    }, "Simpan")));
  ctx.post(() => {
    const map = newMap($("#resmap"));
    let pin = null;
    if (map) map.on("click", e => { f.lat.value = e.latlng.lat.toFixed(6); f.lng.value = e.latlng.lng.toFixed(6); pin ? pin.setLatLng(e.latlng) : (pin = L.marker(e.latlng, { icon: dotIcon("#0a64b8") }).addTo(map)); });
  });
}
