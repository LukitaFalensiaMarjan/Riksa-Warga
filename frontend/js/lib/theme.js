import { h } from "./dom.js";
import { icon } from "./icons.js";
import { store } from "./store.js";

// Tema terang/gelap: pilihan pengguna disimpan di perangkat; bila belum memilih, ikut pengaturan sistem.
const KEY = "rw_theme";
export const theme = () => store.get(KEY) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
export const applyTheme = () => { document.documentElement.dataset.theme = theme(); };

export function themeBtn() {
  const b = h("button", { class: "theme-btn", type: "button", onclick: () => {
    store.set(KEY, theme() === "dark" ? "light" : "dark"); applyTheme();
    document.querySelectorAll(".theme-btn").forEach(paint);
  } });
  paint(b);
  return b;
}
function paint(b) {
  const dark = theme() === "dark";
  b.replaceChildren(icon(dark ? "sun" : "moon"));
  b.title = b.ariaLabel = dark ? "Ganti ke mode terang" : "Ganti ke mode gelap";
}
