from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .deps import current_store, require_perm
from .models import Category, Product, User
from .schemas import CategoryIn, ProductIn, ProductOut

router = APIRouter(prefix="/api", tags=["catalog"])


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
    p = Product(company_id=user.company_id, store_id=store.id, **body.model_dump())
    db.add(p)
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
    p = db.get(Product, product_id)
    if not p or p.company_id != user.company_id:
        raise HTTPException(404, "Mahsulot topilmadi")
    for key, val in body.model_dump().items():
        setattr(p, key, val)
    db.commit()
    db.refresh(p)
    return product_out(p)


@router.post("/products/{product_id}/toggle", response_model=ProductOut)
def toggle_product(
    product_id: int,
    user: User = Depends(require_perm("products")),
    db: Session = Depends(get_db),
):
    p = db.get(Product, product_id)
    if not p or p.company_id != user.company_id:
        raise HTTPException(404, "Mahsulot topilmadi")
    p.is_active = not p.is_active
    db.commit()
    db.refresh(p)
    return product_out(p)
