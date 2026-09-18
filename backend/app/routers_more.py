from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .deps import current_store, forbid_company_kirim_write, get_current_user, require_perm
from .ledger import customer_ledger
from .models import CashTxn, Company, Customer, Expense, Store, User
from .schemas import CustomerIn, DebtPayIn, ExpenseIn, SettingsIn

router = APIRouter(prefix="/api", tags=["more"])


@router.get("/customers")
def list_customers(user: User = Depends(require_perm("customers")), db: Session = Depends(get_db)):
    rows = db.query(Customer).filter(Customer.company_id == user.company_id).order_by(Customer.name).all()
    return [
        {"id": c.id, "name": c.name, "phone": c.phone, "email": getattr(c, "email", "") or "", "note": c.note, "debt": c.debt, "credit_limit": getattr(c, "credit_limit", 0) or 0}
        for c in rows
    ]


@router.post("/customers")
def create_customer(
    body: CustomerIn,
    user: User = Depends(require_perm("customers")),
    db: Session = Depends(get_db),
):
    c = Customer(
        company_id=user.company_id,
        name=body.name.strip(),
        phone=body.phone.strip(),
        email=getattr(body, "email", "") or "",
        note=body.note,
        credit_limit=getattr(body, "credit_limit", 0) or 0,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "phone": c.phone, "debt": c.debt, "credit_limit": c.credit_limit}


@router.post("/customers/{customer_id}/pay-debt")
def pay_debt(
    customer_id: int,
    body: DebtPayIn,
    user: User = Depends(require_perm("customers")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != user.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    if body.amount <= 0 or body.amount > (c.debt or 0) + 0.01:
        raise HTTPException(400, "Summa noto'g'ri")
    store = current_store(user, db)
    customer_ledger(db, c, -body.amount, user=user, kind="PAY", note=f"Qarz: {c.name}")
    if body.method.upper() == "CASH":
        db.add(
            CashTxn(
                company_id=user.company_id,
                store_id=store.id,
                kind="IN",
                amount=body.amount,
                note=f"Qarz: {c.name}",
            )
        )
    db.commit()
    return {"ok": True, "debt": c.debt}


@router.get("/expenses")
def list_expenses(user: User = Depends(require_perm("cash")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    rows = (
        db.query(Expense)
        .filter(Expense.company_id == user.company_id, Expense.store_id == store.id)
        .order_by(Expense.id.desc())
        .limit(80)
        .all()
    )
    return [
        {
            "id": e.id,
            "category": e.category,
            "amount": e.amount,
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.post("/expenses")
def create_expense(
    body: ExpenseIn,
    user: User = Depends(require_perm("cash")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    cash = 0.0
    for t in db.query(CashTxn).filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id):
        cash += t.amount if t.kind in ("SALE", "IN") else -t.amount
    if body.amount > cash + 0.01:
        raise HTTPException(400, "Kassada yetarli naqd yo'q")
    exp = Expense(
        company_id=user.company_id,
        store_id=store.id,
        category=body.category,
        amount=body.amount,
        note=(body.note or "").strip(),
    )
    db.add(exp)
    db.flush()
    db.add(
        CashTxn(
            company_id=user.company_id,
            store_id=store.id,
            kind="OUT",
            amount=body.amount,
            note=f"Xarajat: {exp.category}" + (f" — {exp.note}" if exp.note else ""),
        )
    )
    db.commit()
    db.refresh(exp)
    return {
        "id": exp.id,
        "category": exp.category,
        "amount": exp.amount,
        "note": exp.note,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "cash_out": True,
    }


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = db.get(Company, user.company_id)
    store = current_store(user, db)
    return {
        "company_name": company.name if company else "",
        "plan": company.plan if company else "FREE",
        "phone": getattr(company, "phone", "") or "",
        "address": getattr(company, "address", "") or "",
        "inn": getattr(company, "inn", "") or "",
        "store_id": store.id,
        "store_name": store.name,
        "store_address": store.address or "",
        "store_phone": getattr(store, "phone", "") or "",
        "currency": getattr(company, "currency", "UZS") or "UZS",
        "vat_percent": float(getattr(company, "vat_percent", 0) or 0),
        "locale": getattr(company, "locale", "uz") or "uz",
        "timezone": getattr(company, "timezone", "Asia/Tashkent") or "Asia/Tashkent",
        "country": getattr(company, "country", "UZ") or "UZ",
    }


@router.patch("/settings")
def patch_settings(
    body: SettingsIn,
    user: User = Depends(require_perm("settings")),
    db: Session = Depends(get_db),
):
    company = db.get(Company, user.company_id)
    store = current_store(user, db)
    if body.company_name is not None and body.company_name.strip():
        company.name = body.company_name.strip()
    if body.phone is not None:
        company.phone = body.phone
    if body.address is not None:
        company.address = body.address
    if body.inn is not None:
        company.inn = body.inn
    if body.store_name:
        store.name = body.store_name.strip()
    if body.store_address is not None:
        store.address = body.store_address
    if body.store_phone is not None:
        store.phone = body.store_phone
    if body.currency:
        company.currency = body.currency.upper()[:8]
    if body.vat_percent is not None:
        company.vat_percent = max(0.0, float(body.vat_percent))
    if body.locale:
        company.locale = body.locale[:8]
    db.commit()
    return get_settings(user, db)
