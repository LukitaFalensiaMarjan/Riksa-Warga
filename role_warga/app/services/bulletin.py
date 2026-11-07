"""Buletin kondisi sungai pos pantau: ringkasan live monitoring semua pos + peringatan dini, disiarkan ke Telegram.

Peringatan dini = PERKIRAAN berbasis aturan sederhana (status, tren, laju naik, hulu -> hilir), bukan kepastian.
Ambang jam di bawah adalah asumsi uji (PRD D-05)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Station
from app.services import weather_live
from app.services.announce import SEVERITY_ACTION
from app.services.messages import APP, FOOTER, fmt_time
from app.services.nature import station_nature

ETA_SHOW_H = 6.0  # perkiraan waktu hanya ditampilkan bila <= 6 jam
LIVE_RAIN_MM_H = 1.0
ICON = {"meluap": "🔴", "waspada": "🟠", "normal": "🟢"}
RANK = {"normal": 0, "waspada": 1, "meluap": 2}


def _status(n: dict) -> str:
    return {"bahaya": "meluap", "waspada": "waspada", "normal": "normal"}.get(n["level_status"], "data_lama")


def _short(name: str) -> str:
    return name.removeprefix("Pos Pantau ")


def _warnings(n: dict, status: str) -> list[str]:
    """Apa yang mungkin terjadi ke depan di satu pos."""
    river, rate, level = n["river_name"] or "sungai", n["rate_cm_per_hour"], n["level_cm"]
    rising = n["trend"] == "naik" and rate is not None and rate > 0
    if status == "data_lama":
        return ["Data tinggi air belum diperbarui; cek langsung ke lokasi."]
    if status == "meluap":
        out = [f"Air di atas ambang bahaya: genangan/banjir di permukiman bantaran {river} sangat mungkin terjadi "
               "dan arus deras berbahaya untuk dilalui."]
        if rising:
            out.append(f"Air masih naik ±{rate:g} cm/jam: luapan berpotensi meluas ke jalan dan rumah terdekat.")
        elif n["trend"] == "turun":
            out.append("Air mulai turun, tetapi genangan, lumpur, dan arus sisa masih berbahaya.")
        return out
    if status == "waspada":
        if rising and level is not None:
            eta = round((n["danger_cm"] - level) / rate, 1)
            if eta <= ETA_SHOW_H:
                return [f"Diperkirakan mencapai ambang bahaya (meluap) ±{eta:g} jam lagi bila laju naik bertahan."]
        return [f"Air di atas ambang waspada: {river} berpotensi meluap bila hujan di hulu berlanjut."]
    eta = n["eta_to_warning_hours"]
    if eta is not None and eta <= ETA_SHOW_H:
        return [f"Air naik: diperkirakan mencapai ambang waspada ±{eta:g} jam lagi."]
    return ["Tidak ada tanda kenaikan berarti dalam beberapa jam ke depan."]


def build(db: Session, now: datetime, note: str | None = None) -> dict:
    stations = list(db.scalars(select(Station).order_by(Station.id)))
    rows = []
    for st in stations:
        n = station_nature(db, st, now)
        status = _status(n)
        rows.append({"id": st.id, "name": st.name, "river_name": st.river_name, "is_upstream": st.is_upstream,
                     "level_cm": n["level_cm"], "warning_cm": st.warning_cm, "danger_cm": st.danger_cm,
                     "status": status, "trend": n["trend"], "rate_cm_per_hour": n["rate_cm_per_hour"],
                     "simulation": n["level_mode"] == "simulation", "warnings": _warnings(n, status)})
    # hulu naik -> banjir kiriman ke pos hilir di sungai yang sama
    for up in (r for r in rows if r["is_upstream"] and r["status"] in ("waspada", "meluap")):
        for down in (r for r in rows if not r["is_upstream"] and r["river_name"] == up["river_name"]):
            down["warnings"] = [w for w in down["warnings"] if not w.startswith("Tidak ada tanda")]
            down["warnings"].append(f"Hulu {up['river_name']} ({_short(up['name'])}) {up['status'].upper()}: "
                                    "waspada banjir kiriman dalam beberapa jam ke depan.")

    weather = weather_live.current()
    rain = weather.get("rain_mm_per_hour") if weather.get("status") == "ok" else None
    worst = max((RANK.get(r["status"], 0) for r in rows), default=0)
    severity = {2: "meluap", 1: "waspada", 0: "informasi"}[worst]
    count = {s: sum(r["status"] == s for r in rows) for s in ("meluap", "waspada", "normal", "data_lama")}
    simulation = any(r["simulation"] for r in rows)

    head = {"meluap": "SUNGAI MELUAP", "waspada": "WASPADA", "informasi": "KONDISI AMAN"}[severity]
    lines = [f"{'[SIMULASI] ' if simulation else ''}[{APP} — BULETIN KONDISI SUNGAI: {head}]",
             f"Kota Bandung · {fmt_time(now)}"]
    if rain is not None:
        lines.append(f"Cuaca: {weather.get('description', '-')}, hujan {rain:g} mm/jam, "
                     f"{weather.get('temperature_c', '-')}°C (Open-Meteo)")
    lines += ["", "RINGKASAN: " + " · ".join(f"{v} {k.replace('_', ' ')}" for k, v in count.items() if v), "",
              "KONDISI TIAP POS"]
    for r in rows:
        level = f"{r['level_cm']:g} cm" if r["level_cm"] is not None else "tanpa data"
        trend = {"naik": "naik ↑", "turun": "turun ↓", "stabil": "stabil"}.get(r["trend"], "")
        lines.append(f"{ICON.get(r['status'], '⚪')} {_short(r['name'])} ({r['river_name'] or '-'}, "
                     f"{'hulu' if r['is_upstream'] else 'hilir'}): {level} — {r['status'].replace('_', ' ').upper()} "
                     f"(waspada ≥{r['warning_cm']:g}, bahaya ≥{r['danger_cm']:g})" + (f" · {trend}" if trend else ""))
    lines += ["", "PERINGATAN DINI (perkiraan)"]
    for r in sorted(rows, key=lambda r: -RANK.get(r["status"], 0)):
        for w in r["warnings"]:
            lines.append(f"• {_short(r['name'])}: {w}")
    if rain is not None and rain >= LIVE_RAIN_MM_H:
        lines.append(f"• Hujan sedang turun {rain:g} mm/jam: tinggi air dapat naik lebih cepat.")
    if note:
        lines += ["", f"Catatan pos pantau: {note}"]
    lines += ["", f"Tindakan: {SEVERITY_ACTION[severity]}",
              "Peringatan dini adalah perkiraan, bukan kepastian, dan bukan perintah evakuasi resmi. " + FOOTER]
    return {"generated_at": now, "severity": severity, "simulation": simulation, "counts": count,
            "weather": weather, "stations": rows, "message": "\n".join(lines)}
