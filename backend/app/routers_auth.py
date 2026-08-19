from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .deps import get_current_user
from .models import Category, Company, Product, Store, User
from .schemas import LoginIn, RegisterIn, TokenOut, UserOut
from .security import ROLE_PERMS, create_token, hash_password, verify_password

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
        permissions=sorted(ROLE_PERMS.get(user.role, set())),
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
def register(body: RegisterIn, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Bu login band")

    company = Company(name=body.company_name.strip(), plan="FREE")
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
    db.commit()
    db.refresh(user)
    return TokenOut(access=create_token(user.id, company.id, user.role), user=user_out(db, user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    if not user.is_active:
        raise HTTPException(403, "Foydalanuvchi o'chirilgan")
    return TokenOut(access=create_token(user.id, user.company_id, user.role), user=user_out(db, user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(db, user)
