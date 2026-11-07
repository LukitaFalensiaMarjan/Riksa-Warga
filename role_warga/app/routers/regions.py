from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import area_scope_ids, ensure_region_access, get_current_user, require_role, user_scope_ids
from app.db import get_db
from app.models import Region, Role, User
from app.schemas import RegionCreate, RegionOut

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = select(Region).order_by(Region.id)
    if me.role != Role.ADMIN:
        q = q.where(Region.id.in_(user_scope_ids(db, me)))  # pos pantau: satu kelurahan
    return db.scalars(q).all()


@router.get("/lookup", response_model=list[RegionOut])
def lookup_regions(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Pilihan lokasi kejadian: seluruh kelurahan pengguna (hanya id, nama, level). Pelapor boleh melapor di luar RT-nya."""
    q = select(Region).order_by(Region.id)
    if me.role != Role.ADMIN:
        q = q.where(Region.id.in_(area_scope_ids(db, me.region_id)))
    return db.scalars(q).all()


@router.get("/{region_id}", response_model=RegionOut)
def get_region(region_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, region_id)
    return region


@router.post("", response_model=RegionOut, status_code=status.HTTP_201_CREATED)
def create_region(
    body: RegionCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_role(Role.ADMIN)),
):
    if body.parent_id is not None and db.get(Region, body.parent_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah induk tidak ditemukan")
    region = Region(**body.model_dump())
    db.add(region)
    db.flush()
    log_action(db, actor_id=me.id, action="region.create", entity_type="region",
               entity_id=region.id, new=body.model_dump(mode="json"))
    db.commit()
    return region
