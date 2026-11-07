import { viewAdmin } from "./views/admin/admin.js";
import { viewDashboard } from "./views/koordinator/dashboard.js";
import { viewIncidents } from "./views/koordinator/incidents.js";
import { viewPriorities } from "./views/koordinator/priorities.js";
import { viewRegistrations } from "./views/koordinator/registrations.js";
import { viewReports } from "./views/koordinator/reports.js";
import { viewResidents } from "./views/koordinator/residents.js";
import { viewRouteAdmin } from "./views/koordinator/routeadmin.js";
import { viewTasks } from "./views/koordinator/tasks.js";
import { viewWeather } from "./views/koordinator/weather.js";
import { viewStations } from "./views/pos_pantau/stations.js";
import { viewVerify } from "./views/pos_pantau/verify.js";
import { viewHelpMap } from "./views/tim_sar/helpmap.js";
import { viewSarReports } from "./views/tim_sar/reports.js";
import { viewMyTasks } from "./views/tim_sar/myTasks.js";
import { viewHouseholds } from "./views/koordinator/households.js";
import { viewAlerts } from "./views/umum/alerts.js";
import { viewMapNav } from "./views/umum/mapnav.js";
import { viewNature } from "./views/umum/nature.js";
import { viewNotifications } from "./views/umum/notifications.js";
import { viewReport } from "./views/umum/report.js";
import { viewShelters } from "./views/umum/shelters.js";
import { viewWargaAlerts } from "./views/warga/alerts.js";
import { viewHome } from "./views/warga/home.js";
import { viewMine } from "./views/warga/mine.js";
import { viewWargaMine } from "./views/warga/myReports.js";
import { viewWargaMap } from "./views/warga/peta.js";
import { viewWargaReport } from "./views/warga/report.js";
import { viewWargaShelters } from "./views/warga/shelters.js";
import { me } from "./state.js";

// peran warga memakai tampilan khusus; peran lain tetap tampilan umum
const forWarga = (wargaView, generic, roles = ["warga"]) => (box, ctx) => (roles.includes(me.role) ? wargaView : generic)(box, ctx);
const FIELD = ["warga", "tim_sar", "pos_pantau"];  // peran yang memakai tampilan bergaya warga untuk halaman yang fiturnya sama

export const TABS = {
  beranda: { label: "Beranda", icon: "beranda", render: viewHome },
  dashboard: { label: "Dashboard", icon: "dashboard", render: viewDashboard, refresh: 15000 },
  prioritas: { label: "Prioritas Evakuasi", icon: "target", render: viewPriorities },
  tugas: { label: "Permintaan Bantuan SAR", icon: "tugas", render: viewTasks },
  tugasku: { label: "Tugas Saya", icon: "tugas", render: viewMyTasks, refresh: 20000 },
  incidents: { label: "Kejadian", icon: "kejadian", render: viewIncidents },
  reports: { label: "Laporan Masuk", icon: "inbox", render: viewReports },
  residents: { label: "Data Warga", icon: "warga", render: viewResidents },
  pendaftaran: { label: "Pendaftaran", icon: "check", render: viewRegistrations, refresh: 30000 },
  petarute: { label: "Peta & Rute", icon: "rute", render: viewRouteAdmin },
  peta: { label: "Peta Evakuasi", icon: "peta", render: forWarga(viewWargaMap, viewMapNav, FIELD) },
  shelters: { label: "Shelter", icon: "shelter", render: forWarga(viewWargaShelters, viewShelters, ["warga", "tim_sar"]) },
  pos: { label: "Pos Pantau", icon: "pos", render: viewStations },
  weather: { label: "Cuaca & Aturan", icon: "cuaca", render: viewWeather },
  verif: { label: "Verifikasi Laporan", icon: "check", render: viewVerify, refresh: 30000 },
  hasil: { label: "Laporan Tugas", icon: "list", render: viewSarReports },
  bantuan: { label: "Peta Bantuan", icon: "sos", render: viewHelpMap, refresh: 45000 },
  keluarga: { label: "Data Keluarga", icon: "warga", render: viewHouseholds },
  alam: { label: "Kondisi Alam", icon: "cuaca", render: viewNature, refresh: 60000 },
  notif: { label: "Notifikasi", icon: "inbox", render: viewNotifications, refresh: 30000 },
  alerts: { label: "Peringatan", icon: "alert", render: forWarga(viewWargaAlerts, viewAlerts, FIELD) },
  lapor: { label: "Lapor Kejadian", icon: "lapor", render: forWarga(viewWargaReport, viewReport) },
  mine: { label: "Laporan Saya", icon: "list", render: forWarga(viewWargaMine, viewMine) },
  admin: { label: "Admin", icon: "admin", render: viewAdmin },
};
export function tabsFor(role) {
  const coord = ["dashboard", "alam", "prioritas", "tugas", "incidents", "reports", "residents", "keluarga", "pendaftaran", "petarute", "shelters", "pos", "weather", "alerts", "notif", "lapor"];
  if (role === "admin") return ["admin", "pendaftaran"];
  if (role === "koordinator") return coord;
  if (role === "tim_sar") return ["tugasku", "hasil", "bantuan", "alam", "peta", "alerts", "notif", "shelters"];
  if (role === "pos_pantau") return ["pos", "verif", "alam", "lapor", "peta", "mine", "alerts", "notif"];
  return ["beranda", "alam", "lapor", "peta", "mine", "alerts", "notif", "shelters"];
}
export const ROLE_LABEL = { warga: "Warga", koordinator: "Koordinator Daerah", pos_pantau: "Pos Pantau", tim_sar: "Tim SAR", admin: "Admin" };
