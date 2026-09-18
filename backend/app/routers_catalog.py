from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .audit import write_audit
from .db import get_db
from .deps import current_store, require_perm
from .ledger import move_stock
from .models import Category, Product, User
from .schemas import CategoryIn, ProductIn, ProductOut

router = APIRouter(prefix="/api", tags=["catalog"])


def _ean13(digits12: str) -> str:
    s = sum(int(digits12[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
    return digits12 + str((10 - s % 10) % 10)


def generate_unique_barcode(db, company_id, store_id) -> str:
    import random
    for _ in range(40):
        body = "200" + f"{random.randint(0, 999_999_999):09d}"
        code = _ean13(body)
        exists = db.query(Product).filter(Product.company_id==company_id, Product.store_id==store_id, Product.barcode==code).first()
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
    cat = Category(company_id=user.company_id, name=body.name.strip())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str = "",
    barcode: str = "",
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    query = db.query(Product).filter(Product.company_id == user.company_id, Product.store_id == store.id)
    if barcode.strip():
        query = query.filter(Product.barcode == barcode.strip())
    elif q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)))
    rows = query.order_by(Product.name).all()
    return [product_out(p) for p in rows]


@router.post("/products", response_model=ProductOut)
def create_product(
    body: ProductIn,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    barcode = (body.barcode or "").strip() or generate_unique_barcode(db, user.company_id, store.id)
    dup = (
        db.query(Product)
        .filter(
            Product.company_id == user.company_id,
            Product.store_id == store.id,
            Product.barcode == barcode,
        )
        .first()
    )
    if dup:
        raise HTTPException(409, "Bu barcode allaqachon bor")
    opening = float(body.stock or 0)
    data = body.model_dump()
    data["stock"] = 0
    data["barcode"] = barcode
    p = Product(company_id=user.company_id, store_id=store.id, **data)
    db.add(p)
    db.flush()
    if opening:
        move_stock(db, p, opening, user=user, store_id=store.id, kind="OPENING", ref_type="product", ref_id=p.id)
    db.commit()
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
    requested_stock = data.pop("stock", None)
    barcode = (body.barcode or "").strip() if "barcode" in data else None
    if barcode is None:
        pass
    elif not barcode:
        data.pop("barcode", None)
    else:
        dup = (
            db.query(Product)
            .filter(
                Product.company_id == user.company_id,
                Product.store_id == store.id,
                Product.barcode == barcode,
                Product.id != p.id,
            )
            .first()
        )
        if dup:
            raise HTTPException(409, "Bu barcode allaqachon bor")
        data["barcode"] = barcode
    for key, val in data.items():
        setattr(p, key, val)
    if requested_stock is not None:
        old_stock = float(p.stock or 0)
        new_stock = float(requested_stock or 0)
        delta = round(new_stock - old_stock, 3)
        if abs(delta) > 0.0001:
            move_stock(
                db,
                p,
                delta,
                user=user,
                store_id=store.id,
                kind="ADJUST",
                note="product.patch",
                ref_type="product",
                ref_id=p.id,
            )
            write_audit(
                db,
                user,
                "product.stock.adjust",
                entity="product",
                entity_id=p.id,
                payload={"old": old_stock, "new": float(p.stock or 0), "delta": delta},
            )
    db.commit()
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
