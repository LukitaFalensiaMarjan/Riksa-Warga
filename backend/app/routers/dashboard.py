from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids, region_ancestor_ids, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import Alert, Incident, IncidentStatus, Report, Resident, Role, Station, User, WeatherContext
from app.routers.alerts import visible_alerts
from app.schemas import AlertOut, IncidentOut, StationOut, WeatherOut
from app.services.monitoring import station_view
from app.services.residents import help_queue, status_summary
from app.services.rules import get_rules

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), me: User = Depends(require_role(Role.KOORDINATOR, Role.ADMIN))):
    now = utcnow()
    scope = user_scope_ids(db, me)

    def scoped(q, col):
        return q if scope is None else q.where(col.in_(scope))

    incidents = db.scalars(scoped(select(Incident).where(Incident.status == IncidentStatus.AKTIF),
                                  Incident.region_id).order_by(Incident.last_report_at.desc())).all()
    incident_rows = []
    for inc in incidents:
        row = IncidentOut.model_validate(inc).model_dump(mode="json")
        if inc.pending_since:
            deadline = inc.pending_since + timedelta(minutes=get_rules(db, inc.hazard).waspada_timeout_minutes)
            row["pending_deadline"] = deadline.isoformat()
        incident_rows.append(row)

    reports = db.execute(scoped(select(Report.status, Report.source, Report.source_mode)
                                .where(Report.received_at >= now - timedelta(hours=24)), Report.region_id)).all()

    station_q = select(Station).order_by(Station.id)
    if scope is not None:
        station_q = station_q.where(Station.region_id.in_(area_scope_ids(db, me.region_id)))
    stations = [StationOut.model_validate(station_view(db, s, now)).model_dump(mode="json")
                for s in db.scalars(station_q)]

    weather_q = select(WeatherContext)
    if scope is not None:
        weather_q = weather_q.where(WeatherContext.region_id.in_(scope | set(region_ancestor_ids(db, me.region_id))))

    residents = list(db.scalars(scoped(select(Resident), Resident.region_id)))
    focus = incidents[0].id if incidents else None
    alerts = db.scalars(visible_alerts(db, me).order_by(Alert.id.desc()).limit(10)).all()

    return {
        "generated_at": now.isoformat(),
        "incidents": incident_rows,
        "reports_24h": {
            "total": len(reports),
            "by_status": dict(Counter(r.status.value for r in reports)),
            "by_source": dict(Counter(r.source.value for r in reports)),
            "by_mode": dict(Counter(r.source_mode.value for r in reports)),
        },
        "stations": stations,
        "weather": [WeatherOut.model_validate(w).model_dump(mode="json") for w in db.scalars(weather_q)],
        "residents": {k: (v if k != "by_status" else {s.value: n for s, n in v.items()})
                      for k, v in status_summary(db, residents, focus).items()},
        "help_queue": len(help_queue(db, residents, focus)),
        "recent_alerts": [AlertOut.model_validate(a).model_dump(mode="json") for a in alerts],
    }
