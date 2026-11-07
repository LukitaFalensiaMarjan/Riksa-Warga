import { act, api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmt } from "../../lib/format.js";
import { badge, field, regionOptions, simBadge, table } from "../../lib/ui.js";
import { reload } from "../../router.js";
import { me } from "../../state.js";

// ---------- Cuaca & aturan ----------
export async function viewWeather(box) {
  const [weather, rules, regions] = await Promise.all([api("GET", "/weather"), api("GET", "/rules"), api("GET", "/regions")]);
  const region = h("select", {}, regionOptions(regions, me.region_id, ["kelurahan", "rw", "rt"]));
  const active = h("input", { type: "checkbox", checked: true });
  const desc = h("input", { value: "Peringatan hujan lebat BMKG" });
  const src = h("input", { value: "BMKG (input manual)" });
  const sim = h("input", { type: "checkbox" });
  box.append(h("h2", {}, "Cuaca & Aturan"),
    h("div", { class: "notice" }, "Cuaca hanya faktor pendukung (tidak pernah bukti tunggal banjir). Integrasi BMKG otomatis belum ada; isi manual dari kanal resmi BMKG, atau simulasi."),
    h("div", { class: "cols" },
      h("div", { class: "card" }, h("h3", {}, "Konteks cuaca saat ini"), table([
        { label: "Wilayah", render: w => "#" + w.region_id }, { label: "Aktif", render: w => w.is_active ? badge("AKTIF", "b-warn") : "Tidak" },
        { label: "Keterangan", render: w => w.description }, { label: "Sumber", render: w => [w.source, " ", simBadge(w.source_mode === "simulation")] },
        { label: "Diperbarui", render: w => fmt(w.updated_at) }], weather, "Belum ada.")),
      h("div", { class: "card" }, h("h3", {}, "Atur konteks cuaca"),
        field("Wilayah", region), field("Keterangan", desc), field("Sumber", src),
        h("label", { class: "chk" }, active, "Peringatan cuaca aktif"), h("label", { class: "chk" }, sim, "Data simulasi (hanya dihitung untuk kejadian simulasi)"),
        h("button", {
          onclick: act(async () => {
            await api("PUT", "/weather", { region_id: Number(region.value), is_active: active.checked, description: desc.value, source: src.value, source_mode: sim.checked ? "simulation" : "real" });
            await reload();
          }, "Konteks cuaca disimpan"),
        }, "Simpan"))),
    h("div", { class: "card" }, h("h3", {}, "Parameter aturan eskalasi (asumsi untuk diuji)"),
      rules.map(r => h("details", {}, h("summary", {}, `${r.hazard.toUpperCase()}${r.is_default ? " (default)" : ""}`),
        h("pre", { class: "msg" }, JSON.stringify(r.params, null, 2)), h("p", { class: "muted small-text" }, r.note)))));
}
