import { h } from "./lib/dom.js";
import { stopMaps } from "./lib/map.js";
import { current, main, setCurrent, setTimer, timer } from "./state.js";
import { TABS } from "./tabs.js";

export function stopTimer() { if (timer) clearInterval(timer); setTimer(null); }
export async function show(id) {
  setCurrent(id); stopTimer();
  const tab = TABS[id], tmp = h("div"), posts = [];
  try { await tab.render(tmp, { post: f => posts.push(f) }); }
  catch (e) { tmp.replaceChildren(h("div", { class: "notice bad" }, "Gagal memuat: " + e.message)); }
  if (current !== id || !main?.isConnected) return;
  stopMaps();
  main.replaceChildren(...tmp.childNodes);
  for (const f of posts) await f();
  if (tab.refresh) setTimer(setInterval(() => { if (!document.querySelector("main input:focus, main textarea:focus, main select:focus")) show(id); }, tab.refresh));
}
export function reload() { return show(current); }
