from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .db import get_db
from .deps import current_store, require_perm
from .ledger import move_stock
from .models import Category, Product, User
from .schemas import CategoryIn, ProductIn, ProductOut

router = APIRouter(prefix="/api", tags=["catalog"])

PRODUCT_LIST_DEFAULT = 200
PRODUCT_LIST_MAX = 500


def _ean13(digits12: str) -> str:
    s = sum(int(digits12[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
    return digits12 + str((10 - s % 10) % 10)


def generate_unique_barcode(db, company_id, store_id) -> str:
    import random

    for _ in range(40):
        body = "200" + f"{random.randint(0, 999_999_999):09d}"
        code = _ean13(body)
        exists = (
            db.query(Product)
            .filter(
                Product.company_id == company_id,
                Product.store_id == store_id,
                Product.barcode == code,
            )
            .first()
        )
        if not exists:
            return code
    raise HTTPException(500, "Barcode yaratib bo'lmadi")


def product_out(p: Product) -> ProductOut:
    return ProductOut(
        id=p.id,
        name=p.name,
        sku=p.sku or "",
        barcode=p.barcode or "",
        category_id=p.category_id,
        category_name=p.category.name if p.category else None,
        unit=p.unit,
        buy_price=p.buy_price,
        sell_price=p.sell_price,
        stock=p.stock,
        min_stock=p.min_stock,
        manufacturer=p.manufacturer or "",
        vat_rate=getattr(p, "vat_rate", None),
        is_active=p.is_active,
    )


def _resolve_category(db: Session, user: User, category_id):
    if category_id in (None, "", 0):
        return None
    try:
        cid = int(category_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Kategoriya noto'g'ri")
    cat = db.get(Category, cid)
    if not cat or cat.company_id != user.company_id:
        raise HTTPException(400, "Kategoriya topilmadi")
    return cat


def _barcode_taken(db, company_id, store_id, barcode, exclude_id=None) -> bool:
    code = (barcode or "").strip()
    if not code:
        return False
    q = db.query(Product).filter(
        Product.company_id == company_id,
        Product.store_id == store_id,
        Product.barcode == code,
    )
    if exclude_id:
        q = q.filter(Product.id != exclude_id)
    return q.first() is not None


def _sku_taken(db, company_id, store_id, sku, exclude_id=None) -> bool:
    code = (sku or "").strip()
    if not code:
        return False
    q = db.query(Product).filter(
        Product.company_id == company_id,
        Product.store_id == store_id,
        Product.sku == code,
    )
    if exclude_id:
        q = q.filter(Product.id != exclude_id)
    return q.first() is not None


def _commit_product(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Bu barcode yoki SKU allaqachon bor")


@router.get("/categories")
def list_categories(user: User = Depends(require_perm("products")), db: Session = Depends(get_db)):
    rows = db.query(Category).filter(Category.company_id == user.company_id).order_by(Category.name).all()
    return [{"id": c.id, "name": c.name} for c in rows]


@router.post("/categories")
def create_category(
    body: CategoryIn,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Kategoriya nomi bo'sh")
    cat = Category(company_id=user.company_id, name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.get("/products", response_model=list[ProductOut])
def list_products(
    response: Response,
    q: str = "",
    barcode: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(PRODUCT_LIST_DEFAULT, ge=1),
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    limit = min(int(limit), PRODUCT_LIST_MAX)
    page = max(int(page), 1)
    offset = (page - 1) * limit
    base = db.query(Product).filter(Product.company_id == user.company_id, Product.store_id == store.id)
    term = (q or "").strip()
    code = (barcode or "").strip()
    query = base
    if code:
        query = query.filter(Product.barcode == code)
    elif term:
        exact = base.filter(Product.barcode == term)
        if exact.limit(1).first() is not None:
            query = exact
        else:
            like = f"%{term}%"
            query = query.filter(
                or_(
                    Product.name.ilike(like),
                    Product.barcode.ilike(like),
                    Product.sku.ilike(like),
                )
            )
    total = query.count()
    rows = (
        query.options(joinedload(Product.category))
        .order_by(Product.name, Product.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Limit"] = str(limit)
    return [product_out(p) for p in rows]


@router.post("/products", response_model=ProductOut)
def create_product(
    body: ProductIn,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    cat = _resolve_category(db, user, body.category_id)
    sku = (body.sku or "").strip()
    barcode = (body.barcode or "").strip() or generate_unique_barcode(db, user.company_id, store.id)
    if _barcode_taken(db, user.company_id, store.id, barcode):
        raise HTTPException(409, "Bu barcode allaqachon bor")
    if _sku_taken(db, user.company_id, store.id, sku):
        raise HTTPException(409, "Bu SKU allaqachon bor")
    opening = float(body.stock or 0)
    data = body.model_dump()
    data["stock"] = 0
    data["barcode"] = barcode
    data["sku"] = sku
    data["category_id"] = cat.id if cat else None
    p = Product(company_id=user.company_id, store_id=store.id, **data)
    db.add(p)
    db.flush()
    if opening:
        move_stock(db, p, opening, user=user, store_id=store.id, kind="OPENING", ref_type="product", ref_id=p.id)
    _commit_product(db)
    db.refresh(p)
    return product_out(p)


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    body: ProductIn,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    p = db.get(Product, product_id)
    if not p or p.company_id != user.company_id or p.store_id != store.id:
        raise HTTPException(404, "Mahsulot topilmadi")
    data = body.model_dump(exclude_unset=True)
    data.pop("stock", None)
    if "category_id" in data:
        cat = _resolve_category(db, user, data.get("category_id"))
        data["category_id"] = cat.id if cat else None
    if "sku" in data:
        sku = (data.get("sku") or "").strip()
        data["sku"] = sku
        if _sku_taken(db, user.company_id, store.id, sku, exclude_id=p.id):
            raise HTTPException(409, "Bu SKU allaqachon bor")
    barcode = (body.barcode or "").strip() if "barcode" in data else None
    if barcode is None:
        pass
    elif not barcode:
        data.pop("barcode", None)
    else:
        if _barcode_taken(db, user.company_id, store.id, barcode, exclude_id=p.id):
            raise HTTPException(409, "Bu barcode allaqachon bor")
        data["barcode"] = barcode
    for key, val in data.items():
        setattr(p, key, val)
    _commit_product(db)
    db.refresh(p)
    return product_out(p)


@router.post("/products/{product_id}/toggle", response_model=ProductOut)
def toggle_product(
    product_id: int,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    p = db.get(Product, product_id)
    if not p or p.company_id != user.company_id or p.store_id != store.id:
        raise HTTPException(404, "Mahsulot topilmadi")
    p.is_active = not p.is_active
    db.commit()
    db.refresh(p)
    return product_out(p)
