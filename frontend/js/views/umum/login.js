import { api } from "../../lib/api.js";
import { app, h } from "../../lib/dom.js";
import { store } from "../../lib/store.js";
import { boot } from "../../session.js";
import { setToken, token } from "../../state.js";
import { authIllustration } from "./authArt.js";
import { applyTheme, themeBtn } from "../../lib/theme.js";

const DEMO = ["admin", "koord_rw01", "koord_rw02", "pospantau1", "timsar1", "timsar2", "warga1", "warga2", "warga3"];
const cleanMsg = e => String(e.message).replace(/^\d+ — /, "");
const STRENGTH = ["Terlalu pendek", "Lemah", "Cukup", "Kuat", "Sangat kuat"];

function strength(pw) {
  if (pw.length < 8) return pw ? 0 : -1;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter(r => r.test(pw)).length;
  return Math.min(4, 1 + (kinds >= 2) + (kinds >= 3) + (pw.length >= 12));
}

function afield(label, input, hint) {
  return h("label", { class: "af" }, h("span", { class: "af-l" }, label), input, hint ? h("small", { class: "af-h" }, hint) : null);
}

function pwInput(autocomplete, onInput) {
  const input = h("input", { type: "password", autocomplete, required: true, placeholder: "Minimal 8 karakter", oninput: onInput });
  const eye = h("button", {
    type: "button", class: "af-eye", "aria-pressed": "false", "aria-label": "Tampilkan password",
    onclick: () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      eye.textContent = show ? "Sembunyi" : "Lihat";
      eye.setAttribute("aria-pressed", String(show));
      eye.setAttribute("aria-label", show ? "Sembunyikan password" : "Tampilkan password");
    },
  }, "Lihat");
  return { input, box: h("div", { class: "af-pw" }, input, eye) };
}

function svg(tag, attrs, ...kids) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  el.append(...kids);
  return el;
}

const busy = (btn, on) => { btn.disabled = on; btn.classList.toggle("loading", on); };

export function renderLogin() {
  // ---------- masuk ----------
  const lUser = h("input", { autocomplete: "username", required: true, placeholder: "Masukkan username" });
  const lPass = pwInput("current-password");
  lPass.input.placeholder = "Masukkan password";
  const lErr = h("p", { class: "af-err", role: "alert", hidden: true });
  const lBtn = h("button", { class: "ab" }, h("span", {}, "Masuk"));
  const loginForm = h("form", { class: "pane-in", novalidate: true, onsubmit: async ev => {
    ev.preventDefault(); lErr.hidden = true;
    if (!lUser.value.trim() || !lPass.input.value) { lErr.textContent = "Isi username dan password."; lErr.hidden = false; return; }
    busy(lBtn, true);
    try {
      const r = await api("POST", "/auth/login", { username: lUser.value.trim(), password: lPass.input.value }, { login: true });
      setToken(r.access_token); store.set("rw_token", token);
      await boot();
    } catch (e) {
      lErr.textContent = cleanMsg(e); lErr.hidden = false;
      card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
    } finally { busy(lBtn, false); }
  } },
  afield("Username", lUser), afield("Password", lPass.box), lErr, lBtn,
  h("details", { class: "demo" }, h("summary", {}, "Akun demo"),
    h("div", { class: "chips" }, DEMO.map(u => h("button", { type: "button", onclick: () => { lUser.value = u; lPass.input.focus(); } }, u)))));

  // ---------- daftar ----------
  const rName = h("input", { autocomplete: "name", required: true, placeholder: "Nama sesuai KTP" });
  const rUser = h("input", { autocomplete: "username", required: true, placeholder: "huruf kecil, angka, _ dan .",
    oninput: () => { rUser.value = rUser.value.toLowerCase().replace(/[^a-z0-9_.]/g, ""); } });
  const bars = [0, 1, 2, 3].map(() => h("i"));
  const meterText = h("small", { class: "af-h" }, "Gunakan huruf besar, angka, atau simbol agar lebih kuat.");
  const meter = h("div", { class: "meter", "aria-hidden": "true" }, bars);
  const rPass = pwInput("new-password", () => {
    const s = strength(rPass.input.value);
    bars.forEach((b, i) => { b.className = i < s ? "on s" + s : ""; });
    meterText.textContent = s < 0 ? "Gunakan huruf besar, angka, atau simbol agar lebih kuat." : "Kekuatan: " + STRENGTH[s];
  });
  const rRt = h("select", { required: true }, h("option", { value: "" }, "Memuat daftar RT..."));
  const rPhone = h("input", { type: "tel", autocomplete: "tel", placeholder: "Opsional, mis. 0812xxxx" });
  const rErr = h("p", { class: "af-err", role: "alert", hidden: true });
  const rBtn = h("button", { class: "ab" }, h("span", {}, "Kirim pendaftaran"));
  api("GET", "/regions/public", undefined, { login: true }).then(list => {
    rRt.replaceChildren(h("option", { value: "" }, "Pilih RT tempat tinggal"), ...list.map(r => h("option", { value: r.id }, r.name)));
  }).catch(() => rRt.replaceChildren(h("option", { value: "" }, "Daftar RT gagal dimuat, periksa koneksi")));

  const done = h("div", { class: "done", hidden: true, "aria-live": "polite" },
    svg("svg", { viewBox: "0 0 52 52", class: "tick", "aria-hidden": "true" },
      svg("circle", { cx: 26, cy: 26, r: 24, fill: "none", stroke: "currentColor", "stroke-width": 3 }),
      svg("path", { d: "M14 27l8 8 16-17", fill: "none", stroke: "currentColor", "stroke-width": 4, "stroke-linecap": "round", "stroke-linejoin": "round" })),
    h("h3", {}, "Pendaftaran terkirim"),
    h("p", {}, "Koordinator Daerah akan memeriksa data Anda. Setelah disetujui, Anda bisa masuk dengan username dan password tadi."),
    h("button", { class: "ab", type: "button", onclick: () => { setMode("login"); lUser.value = rUser.value; reset(); } }, h("span", {}, "Ke halaman masuk")));
  const regForm = h("form", { class: "pane-in", novalidate: true, onsubmit: async ev => {
    ev.preventDefault(); rErr.hidden = true;
    const problem = rName.value.trim().length < 2 ? "Isi nama lengkap."
      : !/^[a-z0-9_.]{3,64}$/.test(rUser.value) ? "Username 3-64 karakter: huruf kecil, angka, _ atau ."
      : rPass.input.value.length < 8 ? "Password minimal 8 karakter."
      : !rRt.value ? "Pilih RT tempat tinggal Anda." : "";
    if (problem) { rErr.textContent = problem; rErr.hidden = false; return; }
    busy(rBtn, true);
    try {
      await api("POST", "/auth/register", { username: rUser.value, name: rName.value.trim(), password: rPass.input.value,
        region_id: Number(rRt.value), phone: rPhone.value.trim() || null }, { login: true });
      regForm.hidden = true; done.hidden = false; regTitle.textContent = "Terima kasih";
    } catch (e) {
      rErr.textContent = cleanMsg(e); rErr.hidden = false;
      card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
    } finally { busy(rBtn, false); }
  } },
  afield("Nama lengkap", rName), afield("Username", rUser), afield("Password", rPass.box, null), meter, meterText,
  afield("RT tempat tinggal", rRt), afield("Telepon", rPhone), rErr, rBtn);
  const reset = () => { regForm.reset(); bars.forEach(b => { b.className = ""; }); regForm.hidden = false; done.hidden = true; rErr.hidden = true; regTitle.textContent = "Daftar"; };

  // ---------- kerangka ----------
  const swap = (mode, text) => h("button", { type: "button", class: "swap", onclick: () => setMode(mode) }, text);
  const loginPane = h("section", { class: "pane pane-login", "aria-labelledby": "t-login" },
    h("h1", { id: "t-login" }, "Masuk"), loginForm,
    h("p", { class: "alt" }, "Belum punya akun? ", swap("register", "Daftar sekarang")));
  const regTitle = h("h1", { id: "t-reg" }, "Daftar");
  const regPane = h("section", { class: "pane pane-register", "aria-labelledby": "t-reg" },
    regTitle, regForm, done,
    h("p", { class: "alt" }, "Sudah punya akun? ", swap("login", "Masuk di sini")));

  const caption = (cls, title, text) => h("div", { class: "cap " + cls }, h("b", {}, title), h("span", {}, text));
  const art = h("aside", { class: "auth-art" },
    svg("svg", { class: "art-shape", viewBox: "0 0 100 100", preserveAspectRatio: "none", "aria-hidden": "true" },
      svg("path", { d: "M0 0H80C98 0 92 20 85 38C77 58 98 70 91 100H0Z", fill: "#fff" })),
    h("div", { class: "art-in" },
      h("div", { class: "art-brand" }, h("img", { src: "/icons/logo-64.png", alt: "" }), h("b", {}, "Riksa Warga")),
      h("div", { class: "art-pic" }, authIllustration()),
      h("div", { class: "caps" },
        caption("cap-login", "Saling jaga, saling kabari", "Pantau, peringatkan, dan evakuasi bersama warga RT/RW."),
        caption("cap-register", "Gabung menjaga lingkungan", "Daftar sebagai warga. Koordinator Daerah memverifikasi akun Anda.")),
      h("p", { class: "art-foot" }, "Butuh bantuan? Hubungi Koordinator Daerah Anda.")));
  const bell = art.querySelector(".bell");
  bell.addEventListener("click", () => { bell.classList.remove("ring"); void bell.getBoundingClientRect(); bell.classList.add("ring"); });
  art.addEventListener("pointermove", ev => {
    const r = art.getBoundingClientRect();
    art.style.setProperty("--mx", ((ev.clientX - r.left) / r.width - .5).toFixed(3));
    art.style.setProperty("--my", ((ev.clientY - r.top) / r.height - .5).toFixed(3));
  });
  art.addEventListener("pointerleave", () => { art.style.setProperty("--mx", 0); art.style.setProperty("--my", 0); });

  const card = h("div", { class: "auth-card", "data-mode": "login" }, regPane, art, loginPane);
  card.addEventListener("animationend", ev => { if (ev.animationName === "shake") card.classList.remove("shake"); });

  function setMode(mode) {
    card.dataset.mode = mode;
    loginPane.inert = mode !== "login"; regPane.inert = mode !== "register";
    card.classList.add("switching");
    setTimeout(() => card.classList.remove("switching"), 800);
    setTimeout(() => (mode === "login" ? lUser : rName).focus({ preventScroll: true }), 420);
  }
  regPane.inert = true;

  const bubbles = [[8, 12, 90], [82, 8, 60], [70, 78, 120], [14, 74, 70], [48, 90, 50], [92, 44, 44]]
    .map(([x, y, s], i) => h("i", { class: "bub", style: `left:${x}%;top:${y}%;width:${s}px;height:${s}px;animation-delay:${-i * 2.3}s` }));
  applyTheme();
  app.replaceChildren(h("div", { class: "auth-page" }, h("div", { class: "auth-theme" }, themeBtn()), ...bubbles, card));
  lUser.focus({ preventScroll: true });
}
