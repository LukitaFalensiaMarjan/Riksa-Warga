from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import hash_password, region_scope_ids, require_role
from app.db import get_db
from app.models import AuditLog, Region, Role, User
from app.schemas import AuditLogOut, DeactivateIn, PasswordResetIn, UserCreate, UserOut, UserUpdate

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    me: User = Depends(require_role(Role.ADMIN, Role.KOORDINATOR)),
):
    q = select(User).order_by(User.id)
    if me.role != Role.ADMIN:
        q = q.where(User.region_id.in_(region_scope_ids(db, me.region_id)))
    return db.scalars(q).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_role(Role.ADMIN)),
):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
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
    me: User = Depends(require_role(Role.ADMIN)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun tidak ditemukan")
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


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                me: User = Depends(require_role(Role.ADMIN))):
    """Atur nama, role, wilayah/pos, atau ponsel akun (FR-002). Perubahan role dicatat di audit."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun tidak ditemukan")
    changes = body.model_dump(exclude_unset=True)
    if "region_id" in changes and db.get(Region, changes["region_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    if user.id == me.id and changes.get("role") not in (None, Role.ADMIN):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tidak dapat mengubah role akun sendiri")
    old = {k: (getattr(user, k).value if hasattr(getattr(user, k), "value") else getattr(user, k)) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    log_action(db, actor_id=me.id, action="user.update", entity_type="user", entity_id=user.id, old=old,
               new={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()})
    db.commit()
    return user


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
def reset_password(user_id: int, body: PasswordResetIn, db: Session = Depends(get_db),
                   me: User = Depends(require_role(Role.ADMIN))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun tidak ditemukan")
    user.password_hash = hash_password(body.password)
    log_action(db, actor_id=me.id, action="user.reset_password", entity_type="user", entity_id=user.id)  # sandi tidak dicatat
    db.commit()
    return user
