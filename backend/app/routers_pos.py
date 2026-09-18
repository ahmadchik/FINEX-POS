from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .audit import write_audit
from .db import get_db
from .deps import current_store, require_perm
from .ledger import customer_ledger, move_stock
from .models import CashShift, CashTxn, Company, Customer, Product, Sale, SaleItem, User
from .money import CASHIER_MAX_DISCOUNT_PCT, money2, vat_included
from .plans import is_writable
from .schemas import ReturnIn, SaleCreate

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
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "name": i.name,
                "qty": i.qty,
                "returned_qty": getattr(i, "returned_qty", 0) or 0,
                "price": i.price,
                "line_total": i.line_total,
                "tax": getattr(i, "tax", 0) or 0,
            }
            for i in sale.items
        ],
        "tax_total": getattr(sale, "tax_total", 0) or 0,
        "tax_inclusive": True,
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
    company = db.get(Company, user.company_id)
    if not is_writable(company):
        raise HTTPException(402, "Obuna tugagan. Billing orqali to'lang.")
    store = current_store(user, db)
    key = (body.idempotency_key or "").strip() or None
    if key:
        existing = (
            db.query(Sale)
            .filter(
                Sale.company_id == user.company_id,
                Sale.store_id == store.id,
                Sale.idempotency_key == key,
            )
            .first()
        )
        if existing:
            return sale_payload(existing)
    if user.role == "CASHIER":
        open_shift = (
            db.query(CashShift)
            .filter(CashShift.company_id == user.company_id, CashShift.store_id == store.id, CashShift.status == "OPEN")
            .first()
        )
        if not open_shift:
            raise HTTPException(400, "Avval kassa smenasini oching")
    else:
        open_shift = (
            db.query(CashShift)
            .filter(CashShift.company_id == user.company_id, CashShift.store_id == store.id, CashShift.status == "OPEN")
            .first()
        )

    if money2(body.paid_cash) < 0 or money2(body.paid_card) < 0 or money2(body.paid_online) < 0:
        raise HTTPException(400, "To'lov summasi manfiy bo'lmasin")

    need = defaultdict(float)
    prepared = []
    for item in body.items:
        if item.qty <= 0:
            raise HTTPException(400, "Miqdor noto'g'ri")
        product = db.get(Product, item.product_id)
        if not product or product.company_id != user.company_id or product.store_id != store.id:
            raise HTTPException(404, "Mahsulot topilmadi")
        if not product.is_active:
            raise HTTPException(400, f"{product.name}: mahsulot o'chirilgan")
        price = item.price if item.price is not None else product.sell_price
        if price is None or float(price) < 0:
            raise HTTPException(400, "Narx noto'g'ri")
        line = money2(float(price) * float(item.qty))
        need[product.id] += float(item.qty)
        prepared.append((product, float(item.qty), float(price), line))

    for pid, qty in need.items():
        product = db.get(Product, pid)
        if product.stock + 0.0001 < qty:
            raise HTTPException(400, f"{product.name}: qoldiq yetarli emas ({product.stock})")

    subtotal = money2(sum(line for _p, _q, _pr, line in prepared))
    discount = money2(max(0.0, float(body.discount or 0)))
    if discount > subtotal + 0.01:
        raise HTTPException(400, "Chegirma jamidan oshmasin")
    if user.role == "CASHIER" and subtotal > 0:
        cap = money2(subtotal * CASHIER_MAX_DISCOUNT_PCT / 100)
        if discount > cap + 0.01:
            raise HTTPException(403, f"Kassir chegirmasi {CASHIER_MAX_DISCOUNT_PCT}% dan oshmasin")
    total = money2(max(0.0, subtotal - discount))
    vat = float(company.vat_percent or 0) if company else 0
    tax_total = vat_included(total, vat)
    paid_cash = money2(body.paid_cash)
    paid_card = money2(body.paid_card)
    paid_online = money2(body.paid_online)
    paid = money2(paid_cash + paid_card + paid_online)
    if money2(paid_card + paid_online) > total + 0.01:
        raise HTTPException(400, "Karta/online to'lov jamidan oshmasin")
    credit = 0.0
    customer = None
    if body.customer_id:
        customer = db.get(Customer, body.customer_id)
        if not customer or customer.company_id != user.company_id:
            raise HTTPException(404, "Mijoz topilmadi")
    if paid + 0.01 < total:
        if not (body.allow_credit and customer):
            raise HTTPException(400, "To'lov summasi yetarli emas")
        credit = money2(total - paid)
        limit = float(customer.credit_limit or 0)
        if limit > 0 and (customer.debt or 0) + credit > limit + 0.01:
            raise HTTPException(400, "Mijoz kredit limiti oshdi")
    change = money2(max(0.0, paid_cash - max(0.0, total - paid_card - paid_online - credit)))

    count = db.query(Sale).filter(Sale.company_id == user.company_id).count() + 1
    pay_type = (body.payment_type or "CASH").upper()
    if credit:
        pay_type = "CREDIT"
    elif paid_cash and (paid_card or paid_online):
        pay_type = "MIXED"
    elif paid_card and paid_online:
        pay_type = "MIXED"
    sale = Sale(
        company_id=user.company_id,
        store_id=store.id,
        cashier_id=user.id,
        number=f"CHK-{count:06d}",
        subtotal=subtotal,
        discount=discount,
        total=total,
        paid_cash=paid_cash,
        paid_card=paid_card,
        paid_online=paid_online,
        change_amount=change,
        payment_type=pay_type,
        status="PAID",
        customer_id=customer.id if customer else None,
        on_credit=credit,
        tax_total=tax_total,
        shift_id=open_shift.id if open_shift else None,
        idempotency_key=key,
    )
    db.add(sale)
    db.flush()
    for product, qty, price, line in prepared:
        move_stock(db, product, -qty, user=user, store_id=store.id, kind="SALE", ref_type="sale", ref_id=sale.id)
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                name=product.name,
                qty=qty,
                price=price,
                buy_price=product.buy_price or 0,
                line_total=line,
                tax=vat_included(line, vat),
            )
        )
    if paid_cash > 0:
        db.add(
            CashTxn(
                company_id=user.company_id,
                store_id=store.id,
                kind="SALE",
                amount=money2(paid_cash - change),
                note=sale.number,
                sale_id=sale.id,
            )
        )
    if credit and customer:
        customer_ledger(db, customer, credit, user=user, kind="SALE", note=sale.number, sale_id=sale.id)
    write_audit(
        db,
        user,
        "sale.create",
        entity="sale",
        entity_id=sale.id,
        payload={"total": total, "discount": discount, "tax_total": tax_total, "payment_type": pay_type},
    )
    if discount > 0:
        write_audit(
            db,
            user,
            "sale.discount",
            entity="sale",
            entity_id=sale.id,
            payload={"discount": discount, "subtotal": subtotal, "role": user.role},
        )
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
    store = current_store(user, db)
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != user.company_id or sale.store_id != store.id:
        raise HTTPException(404, "Chek topilmadi")
    return sale_payload(sale)


@router.post("/sales/{sale_id}/return")
def return_sale(
    sale_id: int,
    body: ReturnIn | None = None,
    user: User = Depends(require_perm("pos")),
    db: Session = Depends(get_db),
):
    if user.role == "CASHIER":
        raise HTTPException(403, "Qaytarish uchun manager/admin kerak")
    store = current_store(user, db)
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != user.company_id or sale.store_id != store.id:
        raise HTTPException(404, "Chek topilmadi")
    if sale.status == "RETURNED":
        return sale_payload(sale)
    items_map = {i.id: i for i in sale.items}
    plan = []
    if body and body.items:
        for row in body.items:
            item = items_map.get(row.id)
            if not item:
                raise HTTPException(400, "Qator topilmadi")
            already = float(item.returned_qty or 0)
            remain = float(item.qty) - already
            if row.qty <= 0 or row.qty > remain + 0.0001:
                raise HTTPException(400, f"{item.name}: qaytarish miqdori noto'g'ri")
            plan.append((item, float(row.qty)))
    else:
        for item in sale.items:
            remain = float(item.qty) - float(item.returned_qty or 0)
            if remain > 0:
                plan.append((item, remain))
    if not plan:
        raise HTTPException(400, "Qaytarishga hech narsa yo'q")
    refund_goods = 0.0
    for item, qty in plan:
        share = qty / float(item.qty) if item.qty else 0
        refund_goods += float(item.line_total) * share
        item.returned_qty = round(float(item.returned_qty or 0) + qty, 3)
        product = db.get(Product, item.product_id)
        if product:
            move_stock(
                db,
                product,
                qty,
                user=user,
                store_id=sale.store_id,
                kind="RETURN",
                ref_type="sale",
                ref_id=sale.id,
                note=sale.number,
            )
    ratio = refund_goods / float(sale.subtotal) if sale.subtotal else 1
    refund = money2(float(sale.total) * ratio)
    credit_back = min(float(sale.on_credit or 0), refund)
    cash_back = money2(max(0.0, refund - credit_back))
    if credit_back and sale.customer_id:
        customer = db.get(Customer, sale.customer_id)
        if customer:
            customer_ledger(db, customer, -credit_back, user=user, kind="RETURN", note=sale.number, sale_id=sale.id)
        sale.on_credit = money2(max(0.0, float(sale.on_credit or 0) - credit_back))
    if cash_back > 0:
        db.add(
            CashTxn(
                company_id=sale.company_id,
                store_id=sale.store_id,
                kind="OUT",
                amount=cash_back,
                note=f"Qaytarish {sale.number}",
                sale_id=sale.id,
            )
        )
    fully = all(float(i.returned_qty or 0) + 0.0001 >= float(i.qty) for i in sale.items)
    sale.status = "RETURNED" if fully else "PARTIAL"
    write_audit(
        db,
        user,
        "sale.return",
        entity="sale",
        entity_id=sale.id,
        payload={"refund": refund, "full": fully},
    )
    db.commit()
    db.refresh(sale)
    return sale_payload(sale)
