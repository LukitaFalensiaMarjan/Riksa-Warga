import { h, toast } from "./dom.js";
import { store } from "./store.js";
import { me } from "../state.js";

// Foto profil disimpan di perangkat ini saja (belum ada kolom foto di server).
const key = () => "rw_avatar_" + me?.id;
const initials = n => (n || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();

function shrink(file) {
  return new Promise((ok, fail) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const s = 160, k = Math.max(s / img.width, s / img.height), c = document.createElement("canvas");
      c.width = c.height = s;
      c.getContext("2d").drawImage(img, (s - img.width * k) / 2, (s - img.height * k) / 2, img.width * k, img.height * k);
      URL.revokeObjectURL(url); ok(c.toDataURL("image/jpeg", .85));
    };
    img.onerror = () => fail(new Error("Foto tidak dapat dibaca"));
    img.src = url;
  });
}

function paint(el) {
  const src = store.get(key());
  el.replaceChildren(src ? h("img", { src, alt: "Foto profil" }) : initials(me.name));
}

// Tombol bulat: ketuk untuk mengganti foto.
export function avatar(cls = "") {
  const pick = () => {
    const input = h("input", { type: "file", accept: "image/*" });
    input.onchange = async () => {
      const f = input.files[0]; if (!f) return;
      try { store.set(key(), await shrink(f)); document.querySelectorAll(".av").forEach(paint); toast("Foto profil diperbarui"); }
      catch (e) { toast(e.message, true); }
    };
    input.click();
  };
  const el = h("button", { type: "button", class: "av " + cls, title: "Ganti foto profil", "aria-label": "Ganti foto profil", onclick: pick });
  paint(el);
  return el;
}
