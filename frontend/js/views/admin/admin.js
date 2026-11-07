import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { icon } from "../../lib/icons.js";
import { openModal } from "../../lib/modal.js";
import { field, opts, regionOptions, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";
import { ROLE_LABEL, TABS, tabsFor } from "../../tabs.js";

// ---------- Admin: kelola akun & hak akses (RBAC) ----------
const ROLES = [
  ["warga", "warga", "#1e88f0", "Melapor kejadian, kabari status, lihat peta & shelter"],
  ["koordinator", "dashboard", "#0b5cad", "Verifikasi laporan, prioritas evakuasi, tugas SAR"],
  ["tim_sar", "tugas", "#0e8a9a", "Terima & selesaikan tugas bantuan di lapangan"],
  ["pos_pantau", "pos", "#17a98a", "Catat kondisi sungai, kirim laporan dari pos"],
  ["admin", "admin", "#d98a10", "Kelola akun, aturan eskalasi, audit log"],
];
const RC = Object.fromEntries(ROLES.map(([k, ic, c]) => [k, c]));
const initials = n => (n || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();
const roleBadge = r => h("span", { class: "role-b", style: `--rc:${RC[r] || "#64748b"}` }, ROLE_LABEL[r] || r);

export async function viewAdmin(box) {
  // tiap data dimuat sendiri: bila satu gagal, kerangka halaman tetap tampil dengan pesan galat
  const failed = [];
  const load = (name, path) => api("GET", path).catch(e => { failed.push(`${name}: ${e.message}`); return []; });
  const [users, regions, rules, logs] = await Promise.all([load("Akun", "/users"), load("Wilayah", "/regions"), load("Aturan", "/rules"), load("Audit log", "/audit-logs?limit=100")]);
  const regionName = Object.fromEntries(regions.map(r => [r.id, `${r.name} (${r.level.toUpperCase()})`]));
  let view = "akun", roleF = "semua", statusF = "semua", q = "";

  // ---- popup: buat / ubah akun, reset sandi, nonaktifkan ----
  function userForm(u) {
    const f = { u: h("input", { value: u?.username || "", disabled: !!u }), n: h("input", { value: u?.name || "" }), p: h("input", { type: "password", autocomplete: "new-password" }),
      ph: h("input", { value: "", placeholder: u ? "kosongkan bila tidak diubah" : "opsional" }), tg: h("input", { value: "", placeholder: u ? "kosongkan bila tidak diubah" : "chat ID (opsional)" }) };
    const role = h("select", {}, opts(ROLES.map(r => r[0]).map(k => [k, ROLE_LABEL[k]]), u?.role || (roleF !== "semua" ? roleF : "warga")));
    const region = h("select", {}, regionOptions(regions, u?.region_id ?? me.region_id));
    if (u?.id === me.id) { role.disabled = true; role.title = "Peran akun sendiri tidak dapat diubah"; }
    const close = openModal(u ? `Ubah akun · ${u.username}` : "Tambah akun",
      h("div", { class: "row" }, field("Username (a-z 0-9 _ .)", f.u), field("Nama lengkap", f.n)),
      u ? null : field("Kata sandi (min. 8 karakter)", f.p),
      h("div", { class: "row" }, field("Peran (hak akses)", role), field("Wilayah", region)),
      h("div", { class: "row" }, field("Telepon", f.ph), field("Telegram chat ID", f.tg)),
      h("p", { class: "muted small-text" }, "Peran menentukan menu dan data yang dapat diakses akun ini."),
      h("div", { class: "btns" }, h("button", {
        onclick: act(async () => {
          if (u) {
            const body = { name: f.n.value.trim(), role: role.value, region_id: Number(region.value) };
            if (f.ph.value.trim()) body.phone = f.ph.value.trim();
            if (f.tg.value.trim()) body.telegram_chat_id = f.tg.value.trim();
            await api("PATCH", `/users/${u.id}`, body);
          } else await api("POST", "/users", { username: f.u.value.trim(), name: f.n.value.trim(), password: f.p.value, role: role.value, region_id: Number(region.value), phone: f.ph.value.trim() || null, telegram_chat_id: f.tg.value.trim() || null });
          close(); await reload();
        }, u ? "Akun diperbarui" : "Akun dibuat"),
      }, u ? "Simpan perubahan" : "Buat akun"), h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }
  function resetPw(u) {
    const p = h("input", { type: "password", autocomplete: "new-password" });
    const close = openModal(`Reset kata sandi · ${u.username}`, field("Kata sandi baru (min. 8 karakter)", p),
      h("div", { class: "btns" }, h("button", { onclick: act(async () => { await api("POST", `/users/${u.id}/reset-password`, { password: p.value }); close(); }, "Kata sandi diganti") }, "Ganti kata sandi"),
        h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }
  function deactivate(u) {
    const why = h("input", { placeholder: "mis. pindah domisili" });
    const close = openModal(`Nonaktifkan ${u.username}?`, h("p", { class: "muted small-text" }, "Akun tidak bisa masuk lagi sampai diaktifkan kembali. Alasan dicatat di audit log."), field("Alasan", why),
      h("div", { class: "btns" }, h("button", { class: "danger", onclick: act(async () => { if (!why.value.trim()) throw new Error("Alasan wajib diisi"); await api("POST", `/users/${u.id}/deactivate`, { reason: why.value.trim() }); close(); await reload(); }, "Akun dinonaktifkan") }, "Nonaktifkan"),
        h("button", { class: "ghost", onclick: () => close() }, "Batal")));
  }

  // ---- tab Akun ----
  const list = h("div", { class: "u-list" });
  const cnt = k => users.filter(u => k === "semua" || u.role === k).length;
  const chips = [["semua", "Semua", "#64748b"], ...ROLES.map(([k, , c]) => [k, ROLE_LABEL[k], c])].map(([k, t, c]) =>
    h("button", { type: "button", class: "w-chip" + (k === roleF ? " on" : ""), style: `--rc:${c}`, onclick: ev => { roleF = k; chips.forEach(b => b.classList.toggle("on", b === ev.currentTarget)); draw(); } }, t, h("i", {}, cnt(k))));
  const search = h("input", { type: "search", placeholder: "Cari nama atau username…", oninput: ev => { q = ev.target.value.trim().toLowerCase(); draw(); } });
  const statusSel = h("select", { onchange: ev => { statusF = ev.target.value; draw(); } }, opts([["semua", "Semua status"], ["aktif", "Aktif"], ["nonaktif", "Nonaktif"]]));
  function draw() {
    const rows = users.filter(u => (roleF === "semua" || u.role === roleF) && (statusF === "semua" || (statusF === "aktif") === u.is_active)
      && (!q || u.name.toLowerCase().includes(q) || u.username.includes(q)));
    list.replaceChildren(...(rows.length ? rows.map(u => h("div", { class: "u-row" + (u.is_active ? "" : " off"), style: `--rc:${RC[u.role] || "#64748b"}` },
      h("div", { class: "u-av" }, initials(u.name)),
      h("div", { class: "u-id" }, h("b", {}, u.name, u.id === me.id ? h("em", {}, "Anda") : null), h("small", {}, `@${u.username} · ${regionName[u.region_id] || "#" + u.region_id}`)),
      roleBadge(u.role),
      h("span", { class: "badge " + (u.is_active ? "b-ok" : "b-bad") }, u.is_active ? "AKTIF" : "NONAKTIF"),
      h("div", { class: "u-act" },
        h("button", { class: "sec small", onclick: () => userForm(u) }, "Ubah"),
        h("button", { class: "sec small", onclick: () => resetPw(u) }, "Reset sandi"),
        u.id === me.id ? null : u.is_active ? h("button", { class: "danger small", onclick: () => deactivate(u) }, "Nonaktifkan")
          : h("button", { class: "small", onclick: act(async () => { await api("POST", `/users/${u.id}/activate`); await reload(); }, "Akun diaktifkan") }, "Aktifkan"))))
      : [h("p", { class: "muted", style: "padding:18px 4px" }, "Tidak ada akun yang cocok.")]));
  }
  const matrix = h("div", { class: "role-grid" }, ROLES.map(([k, ic, c, d]) => h("div", { class: "role-card", style: `--rc:${c}` },
    h("div", { class: "role-ico" }, icon(ic)), h("b", {}, ROLE_LABEL[k]), h("small", {}, d),
    h("div", { class: "role-menus" }, tabsFor(k).map(t => h("span", {}, TABS[t].label))))));
  const tabAkun = h("div", {},
    h("div", { class: "u-stats" }, ROLES.map(([k, ic, c]) => h("button", { type: "button", class: "u-stat", style: `--rc:${c}`, onclick: () => chips[1 + ROLES.findIndex(r => r[0] === k)].click() },
      h("span", { class: "u-stat-ico" }, icon(ic)), h("b", {}, cnt(k)), h("small", {}, ROLE_LABEL[k])))),
    h("div", { class: "card" },
      h("div", { class: "u-bar" }, h("h3", {}, "Daftar akun"), h("button", { onclick: () => userForm(null) }, icon("check"), "Tambah akun")),
      h("div", { class: "w-chips" }, chips), h("div", { class: "row u-filter" }, search, statusSel), list),
    h("div", { class: "card" }, h("h3", {}, icon("admin"), "Hak akses per peran"), matrix));
  draw();

  // ---- tab Aturan & Audit ----
  const tabRules = h("div", { class: "card" }, h("h3", {}, "Aturan eskalasi banjir (JSON)"),
    ...rules.filter(r => r.hazard === "banjir").map(r => {
      const ta = h("textarea", { style: "min-height:240px;font-family:monospace;font-size:13px" }); ta.value = JSON.stringify(r.params, null, 2);
      return h("div", {}, ta, h("button", { onclick: act(async () => { await api("PUT", `/rules/${r.hazard}`, JSON.parse(ta.value)); await reload(); }, "Aturan disimpan") }, "Simpan aturan"));
    }));
  const tabAudit = h("div", { class: "card" }, h("h3", {}, "Audit log (100 terakhir)"), table([
    { label: "Waktu", render: l => fmt(l.created_at) }, { label: "Pelaku", render: l => l.actor_id ? "user #" + l.actor_id : "sistem" }, { label: "Aksi", key: "action" },
    { label: "Objek", render: l => `${l.entity_type} ${l.entity_id ?? ""}` }, { label: "Alasan", render: l => l.reason || "-" }], logs));

  const views = { akun: tabAkun, aturan: tabRules, audit: tabAudit };
  const body = h("div"), seg = [["akun", "Akun & hak akses"], ["aturan", "Aturan eskalasi"], ["audit", "Audit log"]].map(([k, t]) =>
    h("button", { type: "button", class: "w-chip" + (k === view ? " on" : ""), onclick: ev => { view = k; seg.forEach(b => b.classList.toggle("on", b === ev.currentTarget)); body.replaceChildren(views[k]); } }, t));
  body.append(views[view]);
  if (failed.length) box.append(h("div", { class: "notice bad" }, h("b", {}, "Sebagian data gagal dimuat. "), failed.join(" · "),
    h("div", { class: "small-text", style: "margin-top:4px" }, "Periksa server API (database dan versi kode), lalu "), h("button", { class: "small", style: "margin-top:6px", onclick: reload }, "Muat ulang")));
  box.append(h("div", { class: "w-head" }, h("h2", {}, "Kelola Pengguna"), h("p", {}, "Atur akun warga, koordinator, Tim SAR, dan pos pantau beserta hak aksesnya.")), h("div", { class: "w-chips" }, seg), body);
}
