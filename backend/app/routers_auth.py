from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from .audit import write_audit
from .db import get_db
from .deps import get_current_user
from .models import Category, Company, Product, Store, User, next_account_no
from .plans import is_writable, refresh_company_status
from .schemas import ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from .security import ROLE_PERMS, client_host, create_token, hash_password, rate_limit, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

DEMO_PRODUCTS = [
    ("Ichimliklar", "Coca Cola 1.5L", "4780000000001", 9000, 12000, 35),
    ("Ichimliklar", "Pepsi 1.5L", "4780000000002", 8500, 11500, 20),
    ("Oziq-ovqat", "Non", "4780000000003", 3000, 4000, 80),
    ("Gigiyena", "Shampun", "4780000000004", 18000, 25000, 12),
]


def user_out(db: Session, user: User) -> UserOut:
    company = db.get(Company, user.company_id)
    store = db.get(Store, user.store_id) if user.store_id else (
        db.query(Store).filter(Store.company_id == user.company_id).first()
    )
    status = refresh_company_status(company) if company else "SUSPENDED"
    stores = []
    if user.role in ("OWNER", "ADMIN") and company:
        stores = [
            {"id": s.id, "name": s.name, "is_active": bool(s.is_active)}
            for s in db.query(Store).filter(Store.company_id == company.id).order_by(Store.id).all()
        ]
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=company.name if company else "",
        store_id=store.id if store else None,
        store_name=store.name if store else None,
        plan=company.plan if company else "FREE",
        account_no=company.account_no if company else None,
        permissions=sorted(ROLE_PERMS.get(user.role, set())),
        currency=(company.currency if company else "UZS") or "UZS",
        locale=(company.locale if company else "uz") or "uz",
        vat_percent=float(company.vat_percent or 0) if company else 0,
        company_status=status,
        trial_ends_at=company.trial_ends_at.isoformat() if company and company.trial_ends_at else None,
        paid_until=company.paid_until.isoformat() if company and company.paid_until else None,
        writable=is_writable(company),
        stores=stores,
        cabinet="company" if user.role in ("OWNER", "ADMIN") else "store",
    )


def seed_catalog(db: Session, company_id: int, store_id: int) -> None:
    cats: dict[str, Category] = {}
    for cat_name, name, barcode, buy, sell, stock in DEMO_PRODUCTS:
        if cat_name not in cats:
            cat = Category(company_id=company_id, name=cat_name)
            db.add(cat)
            db.flush()
            cats[cat_name] = cat
        db.add(
            Product(
                company_id=company_id,
                store_id=store_id,
                category_id=cats[cat_name].id,
                name=name,
                barcode=barcode,
                sku=barcode[-4:],
                buy_price=buy,
                sell_price=sell,
                stock=stock,
                min_stock=10,
                unit="dona",
                is_active=True,
            )
        )


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    rate_limit("reg:" + client_host(request), 5, 300)
    username = body.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Bu login band")

    now = datetime.utcnow()
    company = Company(
        name=body.company_name.strip(),
        plan="FREE",
        status="TRIAL",
        account_no=next_account_no(db),
        trial_ends_at=now + timedelta(days=30),
        currency="UZS",
        locale="uz",
        country="UZ",
    )
    db.add(company)
    db.flush()
    store = Store(company_id=company.id, name=body.store_name.strip() or "Asosiy do'kon")
    db.add(store)
    db.flush()
    user = User(
        company_id=company.id,
        store_id=store.id,
        full_name=body.full_name.strip(),
        username=username,
        password_hash=hash_password(body.password),
        role="OWNER",
    )
    db.add(user)
    seed_catalog(db, company.id, store.id)
    write_audit(db, user, "auth.register", entity="company", entity_id=company.id)
    db.commit()
    db.refresh(user)
    return TokenOut(access=create_token(user.id, company.id, user.role, store.id), user=user_out(db, user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    host = client_host(request)
    username = (body.username or "").strip().lower()
    rate_limit("login-ip:" + host, 40, 60)
    rate_limit("login:" + host + ":" + username, 8, 60)
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    if not user.is_active:
        raise HTTPException(403, "Foydalanuvchi o'chirilgan")
    write_audit(db, user, "auth.login", entity="user", entity_id=user.id)
    db.commit()
    return TokenOut(access=create_token(user.id, user.company_id, user.role, user.store_id), user=user_out(db, user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("pw:" + str(user.id), 8, 60)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Joriy parol noto'g'ri")
    new_pw = body.new_password.strip()
    if len(new_pw) < 6:
        raise HTTPException(400, "Yangi parol kamida 6 belgi")
    if new_pw == body.current_password:
        raise HTTPException(400, "Yangi parol joriydan farq qilsin")
    user.password_hash = hash_password(new_pw)
    write_audit(db, user, "auth.password.change", entity="user", entity_id=user.id)
    db.commit()
    return {"ok": True}
