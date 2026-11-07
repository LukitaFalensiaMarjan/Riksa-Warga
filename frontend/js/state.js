import { store } from "./lib/store.js";

export let token = store.get("rw_token");
export let me = null;
export let cfg = { tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", tile_attribution: "© OpenStreetMap contributors", routing_enabled: true };
export let current = null, timer = null, main = null, netbar = null;
export const setToken = v => { token = v; };
export const setMe = v => { me = v; };
export const setCfg = v => { cfg = v; };
export const setCurrent = v => { current = v; };
export const setTimer = v => { timer = v; };
export const setMain = v => { main = v; };
export const setNetbar = v => { netbar = v; };
