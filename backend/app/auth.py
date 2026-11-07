from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Region, RegionLevel, Role, User

_bearer = HTTPBearer(auto_error=False)
_ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user.id), "role": user.role.value, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid")
    if cred is None:
        raise unauthorized
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=[_ALGO])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    user = db.get(User, user_id)
    # peran dibaca dari DB, bukan token, agar perubahan peran/nonaktif berlaku segera
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_role(*roles: Role):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Peran tidak diizinkan")
        return user

    return dep


def region_scope_ids(db: Session, root_id: int) -> set[int]:
    """root_id beserta semua turunannya (RW -> RT, dst)."""
    ids, frontier = {root_id}, [root_id]
    while frontier:
        children = db.scalars(select(Region.id).where(Region.parent_id.in_(frontier))).all()
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return ids


def region_ancestor_ids(db: Session, region_id: int) -> list[int]:
    """region_id lalu induk-induknya sampai akar (RT -> RW -> kelurahan ...)."""
    ids: list[int] = []
    cur = db.get(Region, region_id)
    while cur is not None and cur.id not in ids:
        ids.append(cur.id)
        cur = db.get(Region, cur.parent_id) if cur.parent_id else None
    return ids


def ancestor_at_level(db: Session, region_id: int, level: RegionLevel) -> int | None:
    for rid in region_ancestor_ids(db, region_id):
        if db.get(Region, rid).level == level:
            return rid
    return None


def area_scope_ids(db: Session, region_id: int) -> set[int]:
    """Seluruh kelurahan tempat region_id berada (untuk pos pantau, shelter, kejadian sekitar)."""
    root = ancestor_at_level(db, region_id, RegionLevel.KELURAHAN) or region_id
    return region_scope_ids(db, root)


def user_scope_ids(db: Session, user: User) -> set[int] | None:
    """None = tanpa batas (admin)."""
    return None if user.role == Role.ADMIN else region_scope_ids(db, user.region_id)


def can_access_region(db: Session, user: User, region_id: int) -> bool:
    if user.role == Role.ADMIN:
        return True
    return region_id in region_scope_ids(db, user.region_id)


def ensure_region_access(db: Session, user: User, region_id: int) -> None:
    if not can_access_region(db, user, region_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Di luar wilayah kewenangan")
