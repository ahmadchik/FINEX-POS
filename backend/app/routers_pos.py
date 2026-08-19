from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .db import get_db
from .deps import current_store, require_perm
from .models import CashTxn, Customer, Product, Sale, SaleItem, User
from .schemas import SaleCreate

router = APIRouter(prefix="/api", tags=["pos"])


def sale_payload(sale: Sale):
    return {
        "id": sale.id,
        "number": sale.number,
        "subtotal": sale.subtotal,
        "discount": sale.discount,
        "total": sale.total,
        "paid_cash": sale.paid_cash,
        "paid_card": sale.paid_card,
        "paid_online": sale.paid_online,
        "on_credit": getattr(sale, "on_credit", 0) or 0,
        "change_amount": sale.change_amount,
        "payment_type": sale.payment_type,
        "status": sale.status,
        "cashier": sale.cashier.full_name if sale.cashier else "",
        "customer_id": getattr(sale, "customer_id", None),
        "customer_name": sale.customer.name if getattr(sale, "customer", None) else "",
        "created_at": sale.created_at.isoformat() if sale.created_at else None,
        "items": [{"name": i.name, "qty": i.qty, "price": i.price, "line_total": i.line_total} for i in sale.items],
    }


@router.get("/pos/products")
def pos_products(
    q: str = "",
    user: User = Depends(require_perm("pos")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    query = db.query(Product).filter(
        Product.company_id == user.company_id,
        Product.store_id == store.id,
        Product.is_active.is_(True),
    )
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)))
    rows = query.order_by(Product.name).limit(80).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "barcode": p.barcode,
            "sell_price": p.sell_price,
            "stock": p.stock,
            "unit": p.unit,
        }
        for p in rows
    ]


@router.post("/pos/sale")
def create_sale(
    body: SaleCreate,
    user: User = Depends(require_perm("pos")),
    db: Session = Depends(get_db),
):
    if not body.items:
        raise HTTPException(400, "Savat bo'sh")
    store = current_store(user, db)

    subtotal = 0.0
    prepared = []
    for item in body.items:
        product = db.get(Product, item.product_id)
        if not product or product.company_id != user.company_id:
            raise HTTPException(404, "Mahsulot topilmadi")
        if item.qty <= 0:
            raise HTTPException(400, "Miqdor noto'g'ri")
        if product.stock < item.qty:
            raise HTTPException(400, f"{product.name}: qoldiq yetarli emas ({product.stock})")
        price = item.price if item.price is not None else product.sell_price
        line = round(price * item.qty, 2)
        subtotal += line
        prepared.append((product, item.qty, price, line))

    discount = max(0.0, float(body.discount or 0))
    total = max(0.0, round(subtotal - discount, 2))
    paid = round(body.paid_cash + body.paid_card + body.paid_online, 2)
    credit = 0.0
    customer = None
    if body.customer_id:
        customer = db.get(Customer, body.customer_id)
        if not customer or customer.company_id != user.company_id:
            raise HTTPException(404, "Mijoz topilmadi")
    if paid + 0.01 < total:
        if not (body.allow_credit and customer):
            raise HTTPException(400, "To'lov summasi yetarli emas")
        credit = round(total - paid, 2)
    change = round(max(0.0, body.paid_cash - max(0.0, total - body.paid_card - body.paid_online - credit)), 2)

    count = db.query(Sale).filter(Sale.company_id == user.company_id).count() + 1
    sale = Sale(
        company_id=user.company_id,
        store_id=store.id,
        cashier_id=user.id,
        number=f"CHK-{count:06d}",
        subtotal=subtotal,
        discount=discount,
        total=total,
        paid_cash=body.paid_cash,
        paid_card=body.paid_card,
        paid_online=body.paid_online,
        change_amount=change,
        payment_type=body.payment_type.upper() if not credit else "CREDIT",
        status="PAID",
        customer_id=customer.id if customer else None,
        on_credit=credit,
    )
    db.add(sale)
    db.flush()
    for product, qty, price, line in prepared:
        product.stock = round(product.stock - qty, 3)
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                name=product.name,
                qty=qty,
                price=price,
                buy_price=product.buy_price or 0,
                line_total=line,
            )
        )
    if body.paid_cash > 0:
        db.add(
            CashTxn(
                company_id=user.company_id,
                store_id=store.id,
                kind="SALE",
                amount=body.paid_cash - change,
                note=sale.number,
                sale_id=sale.id,
            )
        )
    if credit and customer:
        customer.debt = round((customer.debt or 0) + credit, 2)
    db.commit()
    db.refresh(sale)
    return sale_payload(sale)


@router.get("/sales")
def list_sales(
    page: int = 1,
    page_size: int = 20,
    date_from: str = "",
    date_to: str = "",
    cashier: str = "",
    user: User = Depends(require_perm("pos")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    q = (
        db.query(Sale)
        .options(joinedload(Sale.cashier))
        .filter(Sale.company_id == user.company_id, Sale.store_id == store.id)
    )
    if date_from.strip():
        start = datetime.fromisoformat(date_from.strip()[:10])
        q = q.filter(Sale.created_at >= start)
    if date_to.strip():
        end = datetime.fromisoformat(date_to.strip()[:10]) + timedelta(days=1)
        q = q.filter(Sale.created_at < end)
    if cashier.strip():
        like = f"%{cashier.strip()}%"
        q = q.filter(Sale.cashier.has(User.full_name.ilike(like)))
    total = q.order_by(None).count()
    rows = q.order_by(Sale.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    cashiers = [
        name
        for (name,) in (
            db.query(User.full_name)
            .join(Sale, Sale.cashier_id == User.id)
            .filter(Sale.company_id == user.company_id, Sale.store_id == store.id)
            .distinct()
            .order_by(User.full_name)
            .all()
        )
        if name
    ]
    return {
        "items": [
            {
                "id": s.id,
                "number": s.number,
                "total": s.total,
                "payment_type": s.payment_type,
                "cashier": s.cashier.full_name if s.cashier else "",
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "status": s.status,
            }
            for s in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "cashiers": cashiers,
    }


@router.get("/sales/{sale_id}")
def get_sale(sale_id: int, user: User = Depends(require_perm("pos")), db: Session = Depends(get_db)):
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != user.company_id:
        raise HTTPException(404, "Chek topilmadi")
    return sale_payload(sale)


@router.post("/sales/{sale_id}/return")
def return_sale(sale_id: int, user: User = Depends(require_perm("pos")), db: Session = Depends(get_db)):
    if user.role == "CASHIER":
        raise HTTPException(403, "Qaytarish uchun manager/admin kerak")
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != user.company_id:
        raise HTTPException(404, "Chek topilmadi")
    if sale.status == "RETURNED":
        return sale_payload(sale)
    for item in sale.items:
        product = db.get(Product, item.product_id)
        if product:
            product.stock = round(product.stock + item.qty, 3)
    cash_in = sale.paid_cash - (sale.change_amount or 0)
    if cash_in > 0:
        db.add(
            CashTxn(
                company_id=sale.company_id,
                store_id=sale.store_id,
                kind="OUT",
                amount=cash_in,
                note=f"Qaytarish {sale.number}",
                sale_id=sale.id,
            )
        )
    if sale.customer_id and (sale.on_credit or 0) > 0:
        customer = db.get(Customer, sale.customer_id)
        if customer:
            customer.debt = max(0.0, round((customer.debt or 0) - sale.on_credit, 2))
    sale.status = "RETURNED"
    db.commit()
    db.refresh(sale)
    return sale_payload(sale)
