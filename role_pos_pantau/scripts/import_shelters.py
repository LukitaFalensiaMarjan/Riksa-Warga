"""Impor KANDIDAT shelter/titik kumpul nyata Kota Bandung dari OpenStreetMap (Overpass API).

    python -m scripts.import_shelters                 # ke wilayah "RW 01" (demo)
    python -m scripts.import_shelters --region "RW 02" --dry-run
    python -m scripts.import_shelters --file overpass.json   # tanpa internet (hasil Overpass tersimpan)

Aturan (PRD v2 §12.1, D-04):
- Semua hasil masuk sebagai BELUM terverifikasi. Tidak ada yang disebut "aman": koordinator memverifikasi lewat aplikasi
  (tombol Verifikasi) setelah dicek ke pengelola/BPBD. Warga hanya melihat shelter yang sudah diverifikasi.
- Setiap shelter memuat sumbernya (jenis + id OSM, lisensi ODbL) di catatan aksesibilitas.
- Yang diimpor: titik kumpul (emergency=assembly_point), stadion/GOR, dan balai/gedung warga bernama. Halte, pangkalan
  becak, dan tempat komersial sengaja tidak diimpor. Penyaring ini heuristik — tetap perlu verifikasi manusia.
- Pemetaan ke wilayah (--region) hanya untuk demo karena batas RW/kelurahan pilot belum ditetapkan (D-01/D-02).
"""
import argparse
import json
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.models import Region, Shelter, ShelterStatus

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:60];
area["name"="Kota Bandung"]["boundary"="administrative"]->.a;
(
  nwr["emergency"="assembly_point"](area.a);
  nwr["amenity"="community_centre"](area.a);
  nwr["leisure"="stadium"](area.a);
  nwr["leisure"="sports_hall"](area.a);
);
out center tags;"""
EXCLUDE = ("futsal", "dojang", "ballroom", "bee sanctuary", "nutrihub", "coworking", "common room", "softball", "voli pasir")
COMMUNITY_OK = ("balai", "aula", "gedung", "pkm", "kegiatan", "rw", "kelurahan", "kecamatan", "masjid", "gor", "lapang")


def fetch() -> list[dict]:
    r = httpx.post(OVERPASS, data={"data": QUERY}, timeout=90,
                   headers={"User-Agent": "RiksaWarga/0.3 (impor shelter)", "Accept": "application/json"})
    r.raise_for_status()
    return r.json().get("elements", [])


def candidates(elements: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in elements:
        tags = e.get("tags", {})
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        if c.get("lat") is None or c.get("lon") is None:
            continue
        ref = f"OSM {e['type']}/{e['id']}"
        name = (tags.get("name") or "").strip()
        low = name.lower()
        if any(x in low for x in EXCLUDE):
            continue
        if tags.get("emergency") == "assembly_point":
            kind, label = "titik kumpul", name or f"Titik Kumpul ({ref})"
        elif tags.get("leisure") in ("stadium", "sports_hall") and name:
            kind, label = "stadion/gedung olahraga", name
        elif tags.get("amenity") == "community_centre" and name and any(k in low for k in COMMUNITY_OK):
            kind, label = "balai/gedung warga", name
        else:
            continue
        if ref in seen:
            continue
        seen.add(ref)
        address = ", ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber"),
                                        tags.get("addr:suburb") or tags.get("addr:city")) if x)
        out.append({"ref": ref, "kind": kind, "name": label[:120], "lat": float(c["lat"]), "lng": float(c["lon"]),
                    "address": (address or "Alamat belum tercatat (lihat koordinat)")[:255]})
    return out


def save(db: Session, region_name: str, items: list[dict]) -> tuple[int, int]:
    """Idempoten: kandidat dengan id OSM yang sudah ada dilewati."""
    region = db.scalar(select(Region).where(Region.name == region_name))
    if region is None:
        raise SystemExit(f"Wilayah '{region_name}' tidak ada. Jalankan python -m scripts.seed dulu.")
    existing = " ".join(n for n in db.scalars(select(Shelter.accessibility_note)) if n)
    added = skipped = 0
    for it in items:
        if it["ref"] in existing:
            skipped += 1
            continue
        db.add(Shelter(name=it["name"], region_id=region.id, lat=it["lat"], lng=it["lng"], address=it["address"],
                       capacity=None, status=ShelterStatus.TERSEDIA, is_verified=False, updated_at=utcnow(),
                       accessibility_note=(f"{it['kind']}. Sumber: {it['ref']} (OpenStreetMap, ODbL). "
                                           "BELUM diverifikasi lapangan/BPBD.")[:255]))
        added += 1
    db.commit()
    return added, skipped


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", default="RW 01")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file", help="berkas JSON hasil Overpass (tanpa internet)")
    args = ap.parse_args(argv)
    elements = json.load(open(args.file, encoding="utf8")) if args.file else fetch()
    items = candidates(elements)
    print(f"{len(elements)} objek OSM -> {len(items)} kandidat")
    if args.dry_run:
        for it in items:
            print(f"- {it['name']} [{it['kind']}] ({it['lat']:.5f}, {it['lng']:.5f}) {it['ref']}")
        return
    with SessionLocal() as db:
        added, skipped = save(db, args.region, items)
    print(f"Ditambahkan {added}, dilewati {skipped} (sudah ada). Semua BELUM terverifikasi: verifikasi lewat aplikasi.")


if __name__ == "__main__":
    sys.exit(main())
