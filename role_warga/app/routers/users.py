from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import hash_password, region_scope_ids, require_role
from app.db import get_db
from app.models import AuditLog, Region, Role, User
from app.schemas import AuditLogOut, DeactivateIn, UserCreate, UserOut

router = APIRouter(tags=["users"])

# PRD §6.2: koordinator "terbatas pada wilayah" untuk akun. Hanya role di bawahnya, agar tidak bisa menaikkan hak akses.
MANAGEABLE_BY_KOORDINATOR: set = set()  # PRD v2: hanya admin yang mengelola pengguna
account_manager = require_role(Role.ADMIN)


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    me: User = Depends(require_role(Role.ADMIN)),
):
    q = select(User).order_by(User.id)
    if me.role != Role.ADMIN:
        q = q.where(User.region_id.in_(region_scope_ids(db, me.region_id)))
    return db.scalars(q).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    me: User = Depends(account_manager),
):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    if me.role == Role.KOORDINATOR:
        if body.role not in MANAGEABLE_BY_KOORDINATOR:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Koordinator hanya boleh membuat akun warga, relawan, atau pos_pantau")
        if body.region_id not in region_scope_ids(db, me.region_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Wilayah di luar kewenangan")
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username sudah dipakai")

    data = body.model_dump(exclude={"password"})
    user = User(**data, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    log_action(
        db, actor_id=me.id, action="user.create", entity_type="user", entity_id=user.id,
        new={"username": user.username, "role": user.role.value, "region_id": user.region_id},
    )
    db.commit()
    return user


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: int,
    body: DeactivateIn,
    db: Session = Depends(get_db),
    me: User = Depends(account_manager),
):
    user = db.get(User, user_id)
    if user is None or (me.role == Role.KOORDINATOR and user.region_id not in region_scope_ids(db, me.region_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun tidak ditemukan")  # luar wilayah = tidak terlihat
    if me.role == Role.KOORDINATOR and user.role not in MANAGEABLE_BY_KOORDINATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Koordinator tidak boleh menonaktifkan akun peran ini")
    if user.id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tidak dapat menonaktifkan akun sendiri")

    user.is_active = False
    log_action(
        db, actor_id=me.id, action="user.deactivate", entity_type="user", entity_id=user.id,
        old={"is_active": True}, new={"is_active": False}, reason=body.reason,
    )
    db.commit()
    return user


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.ADMIN)),
):
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
