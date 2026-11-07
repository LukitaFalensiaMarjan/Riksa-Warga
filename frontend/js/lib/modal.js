import { $, h } from "./dom.js";

// Popup umum: Esc, klik latar, atau tombol ✕ menutup. Mengembalikan fungsi tutup.
export function openModal(title, ...content) {
  $(".modal-bg")?.remove();
  const prev = document.activeElement;
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const bg = h("div", { class: "modal-bg no-print", onclick: e => { if (e.target === bg) close(); } },
    h("div", { class: "card modal", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "modal-h" }, h("h3", {}, title), h("button", { class: "ghost modal-x", "aria-label": "Tutup", onclick: close }, "✕")), ...content));
  document.addEventListener("keydown", onKey);
  document.body.append(bg);
  bg.querySelector("input,select,textarea")?.focus();
  return close;
}
