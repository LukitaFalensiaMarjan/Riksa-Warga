"""Konteks pendukung mesin aturan: cuaca (input manual BMKG/simulasi) dan parameter aturan."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ensure_region_access, operational_user, region_ancestor_ids, region_scope_ids, require_role
from app.db import get_db, to_utc_naive, utcnow
from app.models import Hazard, Region, Role, RuleConfig, User, WeatherContext
from app.schemas import RuleOut, WeatherIn, WeatherOut
from app.services import engine, forecast, notifier
from app.services.rules import RULES_NOTE, RuleParams, get_rules
from app.services.weather_api import get_bandung_live_weather

router = APIRouter(tags=["konteks & aturan"])
coordinator = require_role(Role.KOORDINATOR, Role.POS_PANTAU, Role.ADMIN)


@router.get("/weather/live")
async def live_weather_api(me: User = Depends(operational_user)):
    """Data cuaca realtime Bandung dari Open-Meteo API (hujan mm/jam, suhu, kelembapan)."""
    return await get_bandung_live_weather()



@router.get("/forecast")
def forecast_risk(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    """Prakiraan hujan + prediksi Potensi Banjir (Rendah/Sedang/Tinggi) beserta alasan, jendela waktu, keyakinan.
    PERKIRAAN BANTU, bukan deteksi banjir (PRD §7.1)."""
    return forecast.predict(db)


@router.get("/weather", response_model=list[WeatherOut])
def list_weather(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = select(WeatherContext).order_by(WeatherContext.id)
    if me.role != Role.ADMIN:
        regions = region_scope_ids(db, me.region_id) | set(region_ancestor_ids(db, me.region_id))
        q = q.where(WeatherContext.region_id.in_(regions))
    return db.scalars(q).all()


@router.put("/weather", response_model=WeatherOut)
@engine.locked
def set_weather(body: WeatherIn, background: BackgroundTasks, db: Session = Depends(get_db),
                me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, body.region_id)
    now = utcnow()
    row = db.scalar(select(WeatherContext).where(WeatherContext.region_id == body.region_id))
    old = None if row is None else {"is_active": row.is_active, "description": row.description}
    if row is None:
        row = WeatherContext(region_id=body.region_id)
        db.add(row)
    row.is_active, row.description, row.source = body.is_active, body.description, body.source
    row.source_mode = body.source_mode
    row.valid_until = to_utc_naive(body.valid_until) if body.valid_until else None
    row.updated_by, row.updated_at = me.id, now
    db.flush()
    log_action(db, actor_id=me.id, action="weather.set", entity_type="weather", entity_id=row.id, old=old,
               new=body.model_dump(mode="json"))
    # cuaca hanya faktor pendukung: evaluasi ulang tidak menaikkan level tanpa syarat laporan & hulu
    alerts = engine.reevaluate_region(db, region_scope_ids(db, body.region_id), now)
    db.commit()
    notifier.schedule(background, db, alerts)
    return row


@router.get("/rules", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db), _: User = Depends(coordinator)):
    return [{"hazard": h, "params": get_rules(db, h).model_dump(mode="json"),
             "is_default": db.get(RuleConfig, h) is None, "note": RULES_NOTE}
            for h in (Hazard.BANJIR, Hazard.KEBAKARAN)]


@router.put("/rules/{hazard}", response_model=RuleOut)
def update_rules(hazard: Hazard, body: RuleParams, db: Session = Depends(get_db),
                 me: User = Depends(require_role(Role.ADMIN))):
    row = db.get(RuleConfig, hazard)
    old = get_rules(db, hazard).model_dump(mode="json")
    params = body.model_dump(mode="json")
    if row is None:
        row = RuleConfig(hazard=hazard, params=params)
        db.add(row)
    row.params, row.updated_by, row.updated_at = params, me.id, utcnow()
    log_action(db, actor_id=me.id, action="rules.update", entity_type="rules", entity_id=hazard.value,
               old=old, new=params)
    db.commit()
    return {"hazard": hazard, "params": params, "is_default": False, "note": RULES_NOTE}
