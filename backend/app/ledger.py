from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Customer, CustomerLedger, Product, StockMovement, User


def move_stock(
    db: Session,
    product: Product,
    qty_delta: float,
    *,
    user: User | None,
    store_id: int,
    kind: str,
    note: str = "",
    ref_type: str = "",
    ref_id: int | None = None,
) -> None:
    qty_delta = float(qty_delta or 0)
    if qty_delta == 0:
        return
    new_qty = round(float(product.stock or 0) + qty_delta, 3)
    if new_qty < -0.0001:
        raise HTTPException(400, f"{product.name}: qoldiq yetarli emas ({product.stock})")
    product.stock = 0.0 if new_qty < 0.0001 else new_qty
    db.add(
        StockMovement(
            company_id=product.company_id,
            store_id=store_id,
            product_id=product.id,
            user_id=user.id if user else None,
            qty=qty_delta,
            balance_after=product.stock,
            kind=kind,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note[:300],
        )
    )


def customer_ledger(
    db: Session,
    customer: Customer,
    amount: float,
    *,
    user: User | None,
    kind: str,
    note: str = "",
    sale_id: int | None = None,
) -> None:
    amount = round(float(amount or 0), 2)
    if amount == 0:
        return
    customer.debt = round(float(customer.debt or 0) + amount, 2)
    if customer.debt < 0:
        customer.debt = 0.0
    db.add(
        CustomerLedger(
            company_id=customer.company_id,
            customer_id=customer.id,
            user_id=user.id if user else None,
            sale_id=sale_id,
            kind=kind,
            amount=amount,
            note=note[:300],
        )
    )
