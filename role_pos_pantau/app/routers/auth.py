import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import create_token, get_current_user, verify_password
from app.db import get_db
from app.models import User
from app.schemas import LoginIn, MeOut, ProfileUpdate, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILS = 5
WINDOW_SECONDS = 300
# shortcut: limiter in-memory per proses, hilang saat restart; pindah ke Redis/DB bila >1 worker
_fails: dict[str, list[float]] = defaultdict(list)


def _recent_fails(username: str) -> list[float]:
    now = time.monotonic()
    recent = [t for t in _fails.get(username, []) if now - t < WINDOW_SECONDS]
    if recent:
        _fails[username] = recent
    else:
        _fails.pop(username, None)  # jangan simpan entri kosong
    return recent


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    if len(_recent_fails(body.username)) >= MAX_FAILS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak percobaan, coba lagi nanti")

    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        # hanya akun nyata yang dilacak: memori dibatasi jumlah akun, dan banjir username acak
        # tidak bisa mengosongkan hitungan akun target
        if user is not None:
            _fails[body.username].append(time.monotonic())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username atau password salah")

    _fails.pop(body.username, None)
    log_action(db, actor_id=user.id, action="login", entity_type="user", entity_id=user.id)
    db.commit()
    return TokenOut(access_token=create_token(user), role=user.role)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=MeOut)
def update_me(body: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    changes = {k: (v or None) for k, v in body.model_dump(exclude_unset=True).items()}
    old = {k: getattr(user, k) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    log_action(db, actor_id=user.id, action="user.profile", entity_type="user", entity_id=user.id,
               old=old, new=changes)
    db.commit()
    return user
