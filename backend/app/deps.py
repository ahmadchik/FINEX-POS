from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Company, Store, User
from .security import decode_token, has_perm

HQ_ROLES = ("OWNER", "ADMIN")
HQ_KIRIM_MSG = "Kompaniya kabinetidan kirim-chiqim o'zgartirilmaydi. Do'kon loginidan kiring."


def is_company_cabinet(user: User) -> bool:
    return user.role in HQ_ROLES


def forbid_company_kirim_write(user: User) -> None:
    if is_company_cabinet(user):
        raise HTTPException(403, HQ_KIRIM_MSG)


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
    if payload.get("role") == "PLATFORM":
        raise HTTPException(401, "Invalid token")
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(401, "Invalid token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "User not found")
    token_cid = payload.get("cid")
    if token_cid is not None:
        try:
            token_cid = int(token_cid)
        except (TypeError, ValueError):
            raise HTTPException(401, "Invalid token")
        if int(user.company_id) != token_cid:
            raise HTTPException(401, "Invalid token")
    company = db.get(Company, user.company_id)
    if not company:
        raise HTTPException(401, "User not found")
    if (company.status or "").upper() == "SUSPENDED":
        raise HTTPException(403, "Kompaniya to'xtatilgan")
    return user


def require_perm(perm: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(403, "Ruxsat yo'q")
        return user

    return checker


def current_store(user: User, db: Session) -> Store:
    if user.role == "STORE":
        store = db.get(Store, user.store_id) if user.store_id else None
        if not store or store.company_id != user.company_id:
            raise HTTPException(400, "Do'kon topilmadi")
        return store
    store = None
    if user.store_id:
        store = db.get(Store, user.store_id)
        if store and store.company_id != user.company_id:
            store = None
    if not store:
        store = db.query(Store).filter(Store.company_id == user.company_id).first()
    if not store:
        raise HTTPException(400, "Do'kon topilmadi")
    return store
