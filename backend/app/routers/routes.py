"""Peta evakuasi: titik bahaya jalan (FR-052), rute evakuasi resmi (FR-053), rute jalan kaki ke shelter."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import city_scope_ids, ensure_region_access, operational_user, require_role
from app.db import get_db, utcnow
from app.models import (
    EvacuationRoute,
    HazardKind,
    Incident,
    IncidentStatus,
    Region,
    RoadCondition,
    Role,
    RouteStatus,
    Shelter,
    User,
)
from app.schemas import EvacRouteIn, EvacRouteOut, EvacRouteStatusIn, RoadConditionIn, RoadConditionOut, ShelterOut
from app.services.evacuation import AVAILABLE
from app.services.geo import haversine_m
from app.services.routing import HAZARD_NEAR_M, INCIDENT_NEAR_M, hazards_near, osrm_routes, straight_line

router = APIRouter(tags=["peta evakuasi"])
coordinator = require_role(Role.KOORDINATOR)
field_reporter = require_role(Role.KOORDINATOR, Role.TIM_SAR, Role.POS_PANTAU)
HAZARD_LABEL = {HazardKind.TERTUTUP: "Jalan tertutup", HazardKind.GENANGAN: "Genangan / banjir",
                HazardKind.API: "Api / kebakaran", HazardKind.POHON: "Pohon tumbang",
                HazardKind.KABEL: "Kabel listrik", HazardKind.LAINNYA: "Bahaya lain"}
ROUTE_LABEL = {RouteStatus.TERVERIFIKASI: "Rute resmi terverifikasi petugas",
               RouteStatus.DAPAT_DILALUI: "Dilaporkan dapat dilalui (belum diverifikasi)",
               RouteStatus.BELUM: "Rute resmi belum diverifikasi", RouteStatus.DITUTUP: "Ditutup / berbahaya"}


def _area(db: Session, me: User) -> set[int] | None:
    return city_scope_ids(db, me.region_id)  # sumber daya kota (shelter, rute, bahaya) terlihat se-kota


def _in_area(q, col, area):
    return q if area is None else q.where(col.in_(area))


def active_hazards(db: Session, area: set[int] | None) -> list[dict]:
    out = [{"kind": rc.kind.value, "label": HAZARD_LABEL[rc.kind] + (f": {rc.note}" if rc.note else ""),
            "lat": rc.lat, "lng": rc.lng, "radius_m": HAZARD_NEAR_M, "id": rc.id, "source": "jalan"}
           for rc in db.scalars(_in_area(select(RoadCondition).where(RoadCondition.is_active.is_(True)),
                                         RoadCondition.region_id, area))]
    out += [{"kind": inc.hazard.value, "label": f"Area kejadian #{inc.id} {inc.hazard.value} ({inc.level.value.upper()})",
             "lat": inc.lat, "lng": inc.lng, "radius_m": INCIDENT_NEAR_M[inc.hazard.value], "id": inc.id,
             "source": "kejadian"}
            for inc in db.scalars(_in_area(select(Incident).where(Incident.status == IncidentStatus.AKTIF),
                                           Incident.region_id, area))]
    return out


# ---------- titik bahaya jalan ----------

@router.get("/road-conditions", response_model=list[RoadConditionOut])
def list_road_conditions(include_resolved: bool = False, db: Session = Depends(get_db),
                         me: User = Depends(operational_user)):
    q = select(RoadCondition).order_by(RoadCondition.id.desc())
    if not include_resolved:
        q = q.where(RoadCondition.is_active.is_(True))
    return db.scalars(_in_area(q, RoadCondition.region_id, _area(db, me))).all()


@router.post("/road-conditions", response_model=RoadConditionOut, status_code=status.HTTP_201_CREATED)
def report_road_condition(body: RoadConditionIn, db: Session = Depends(get_db), me: User = Depends(field_reporter)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    area = _area(db, me)
    if area is not None and body.region_id not in area:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Di luar kelurahan Anda")
    now = utcnow()
    rc = RoadCondition(**body.model_dump(), is_active=True, created_by=me.id, created_at=now, updated_at=now)
    db.add(rc)
    db.flush()
    log_action(db, actor_id=me.id, action="road.report", entity_type="road", entity_id=rc.id,
               new=body.model_dump(mode="json"))
    db.commit()
    return rc


@router.post("/road-conditions/{rc_id}/resolve", response_model=RoadConditionOut)
def resolve_road_condition(rc_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    rc = db.get(RoadCondition, rc_id)
    if rc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Titik bahaya tidak ditemukan")
    ensure_region_access(db, me, rc.region_id)
    rc.is_active, rc.updated_at = False, utcnow()
    log_action(db, actor_id=me.id, action="road.resolve", entity_type="road", entity_id=rc.id,
               old={"is_active": True}, new={"is_active": False})
    db.commit()
    return rc


# ---------- rute evakuasi resmi ----------

@router.get("/evacuation-routes", response_model=list[EvacRouteOut])
def list_evac_routes(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = select(EvacuationRoute).order_by(EvacuationRoute.id)
    return db.scalars(_in_area(q, EvacuationRoute.region_id, _area(db, me))).all()


@router.post("/evacuation-routes", response_model=EvacRouteOut, status_code=status.HTTP_201_CREATED)
def create_evac_route(body: EvacRouteIn, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None or db.get(Shelter, body.shelter_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah atau shelter tidak ditemukan")
    ensure_region_access(db, me, body.region_id)
    route = EvacuationRoute(name=body.name, region_id=body.region_id, shelter_id=body.shelter_id,
                            points=[list(p) for p in body.points], status=RouteStatus.BELUM, note=body.note,
                            created_by=me.id, updated_at=utcnow())
    db.add(route)
    db.flush()
    log_action(db, actor_id=me.id, action="route.create", entity_type="route", entity_id=route.id,
               new={"name": body.name, "shelter_id": body.shelter_id, "titik": len(body.points)})
    db.commit()
    return route


@router.post("/evacuation-routes/{route_id}/status", response_model=EvacRouteOut)
def set_evac_route_status(route_id: int, body: EvacRouteStatusIn, db: Session = Depends(get_db),
                          me: User = Depends(coordinator)):
    route = db.get(EvacuationRoute, route_id)
    if route is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rute tidak ditemukan")
    ensure_region_access(db, me, route.region_id)
    old = route.status
    route.status, route.note, route.updated_at = body.status, body.note or route.note, utcnow()
    if body.status == RouteStatus.TERVERIFIKASI:
        route.verified_by, route.verified_at = me.id, utcnow()
    log_action(db, actor_id=me.id, action="route.status", entity_type="route", entity_id=route.id,
               old={"status": old.value}, new={"status": body.status.value}, reason=body.note)
    db.commit()
    return route


# ---------- rute ke shelter ----------

@router.get("/routing/shelter")
def route_to_shelter(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                     shelter_id: int | None = None, db: Session = Depends(get_db),
                     me: User = Depends(operational_user)):
    area = _area(db, me)
    shelters = list(db.scalars(_in_area(select(Shelter).where(Shelter.is_verified.is_(True),
                                                                 Shelter.status.in_(AVAILABLE)),
                                        Shelter.region_id, area)))
    if shelter_id is not None:
        shelters = [s for s in shelters if s.id == shelter_id]
        if not shelters:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Shelter tidak tersedia / belum terverifikasi")
    candidates = sorted(shelters, key=lambda s: haversine_m(lat, lng, s.lat, s.lng))[:2]
    hazards = active_hazards(db, area)
    options = []
    for s in candidates:
        routes = osrm_routes(lat, lng, s.lat, s.lng)
        source = "osrm" if routes else "garis_lurus"
        for rt in (routes := routes or [straight_line(lat, lng, s.lat, s.lng)]):
            rt["hazards"] = hazards_near(rt["points"], hazards)
        best = min(routes, key=lambda r: (len(r["hazards"]), r["duration_s"]))
        warnings = [f"Rute melewati/dekat: {h['label']} (±{h['distance_m']} m)" for h in best["hazards"]]
        warnings += [f"Shelter dekat {h['label']}" for h in hazards_near([[s.lat, s.lng]], hazards)]
        options.append({
            "shelter": ShelterOut.model_validate(s).model_dump(mode="json"), "source": source, **best,
            "alternatives_checked": len(routes),
            "label": ("Rute jalan dari peta umum — BELUM diverifikasi aman" if source == "osrm"
                      else "Garis lurus (tanpa data jalan) — hanya petunjuk arah"),
            "warnings": warnings,
        })
    options.sort(key=lambda o: (len(o["warnings"]), o["duration_s"]))
    official = db.scalars(select(EvacuationRoute).where(
        EvacuationRoute.shelter_id.in_([s.id for s in candidates] or [0]))).all()
    return {
        "from": [lat, lng], "options": options, "hazards": hazards,
        "official_routes": [{**EvacRouteOut.model_validate(r).model_dump(mode="json"), "label": ROUTE_LABEL[r.status]}
                            for r in official],
        "note": "Ikuti arahan petugas. Rute terpendek belum tentu aman; utamakan rute resmi terverifikasi.",
    }


@router.get("/routing/point")
def route_to_point(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                   to_lat: float = Query(ge=-90, le=90), to_lng: float = Query(ge=-180, le=180),
                   db: Session = Depends(get_db), me: User = Depends(operational_user)):
    """Rute jalan kaki titik-ke-titik (mis. Tim SAR menuju warga). Rute umum, bukan jaminan aman."""
    hazards = active_hazards(db, _area(db, me))
    routes = osrm_routes(lat, lng, to_lat, to_lng)
    source = "osrm" if routes else "garis_lurus"
    for rt in (routes := routes or [straight_line(lat, lng, to_lat, to_lng)]):
        rt["hazards"] = hazards_near(rt["points"], hazards)
    best = min(routes, key=lambda r: (len(r["hazards"]), r["duration_s"]))
    warnings = [f"Rute melewati/dekat: {h['label']} (±{h['distance_m']} m)" for h in best["hazards"]]
    return {"from": [lat, lng], "to": [to_lat, to_lng], "source": source, **best, "warnings": warnings,
            "label": ("Rute jalan dari peta umum — BELUM diverifikasi aman" if source == "osrm"
                      else "Garis lurus (tanpa data jalan) — hanya petunjuk arah")}
