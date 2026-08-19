from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Store, User
from .security import decode_token, has_perm


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(401, "Invalid token")
    user = db.get(User, int(payload.get("sub", 0)))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found")
    return user


def require_perm(perm: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(403, "Ruxsat yo'q")
        return user

    return checker


def current_store(user: User, db: Session) -> Store:
    store = None
    if user.store_id:
        store = db.get(Store, user.store_id)
    if not store:
        store = db.query(Store).filter(Store.company_id == user.company_id).first()
    if not store:
        raise HTTPException(400, "Do'kon topilmadi")
    return store
