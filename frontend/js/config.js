
export const DEMO_CENTER = [-6.8830, 107.6110];
export const PRESETS = [
  ["Hulu 1 (dekat pos hulu)", -6.8805, 107.6102, "RT 01 / RW 01"],
  ["Hulu 2", -6.8812, 107.6106, "RT 01 / RW 01"],
  ["Hulu 3", -6.8798, 107.6095, "RT 01 / RW 01"],
  ["Hilir 1", -6.9002, 107.6151, "RT 01 / RW 02"],
  ["Hilir 2", -6.9008, 107.6155, "RT 01 / RW 02"],
  ["Hilir 3", -6.8998, 107.6146, "RT 01 / RW 02"],
];
export const LABEL = {
  aman_mandiri: "Saya Aman (laporan mandiri)", aman_terverifikasi: "Aman Terverifikasi",
  belum_terkonfirmasi: "Belum Terkonfirmasi", butuh_bantuan: "Butuh Bantuan",
  dalam_penanganan: "Dalam Penanganan", dalam_perjalanan: "Dalam Perjalanan",
  tiba_di_titik_aman: "Tiba di Titik Aman", tidak_dapat_dihubungi: "Tidak Dapat Dihubungi",
  belum_diverifikasi: "BELUM DIVERIFIKASI", terverifikasi: "Terverifikasi",
  data_kedaluwarsa: "Data kedaluwarsa", tidak_ada_data: "Belum ada data",
  pos_pantau: "Pos pantau", simulation: "SIMULASI", real: "Nyata",
  menunggu_penerimaan: "Menunggu diterima", diterima: "Diterima", menuju_lokasi: "Menuju lokasi",
  baru: "Belum ditugaskan", selesai: "Selesai", gagal: "Gagal", dibatalkan: "Dibatalkan",
  jalan_tertutup: "Jalan tertutup", genangan: "Genangan / banjir", pohon_tumbang: "Pohon tumbang",
  kabel_listrik: "Kabel listrik", dilaporkan_dapat_dilalui: "Dilaporkan dapat dilalui",
};
export const lab = v => LABEL[v] || String(v ?? "").replaceAll("_", " ");
export const LEVEL_RANK = { pantau: 1, waspada: 2, siaga: 3, evakuasi: 4 };
export const PRIO_COLOR = { kritis: "#dc2626", tinggi: "#ea580c", sedang: "#d97706", rendah: "#0e7c86" };
export const LEVEL_COLOR = { pantau: "#64748b", waspada: "#d97706", siaga: "#ea580c", evakuasi: "#dc2626" };
