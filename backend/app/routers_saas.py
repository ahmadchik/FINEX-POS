from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .audit import write_audit
from .config import settings
from .db import get_db
from .deps import current_store, forbid_company_kirim_write, get_current_user, require_perm
from .ledger import customer_ledger, move_stock
from .models import (
    BillingPayment,
    CashShift,
    CashTxn,
    Company,
    Customer,
    CustomerLedger,
    Product,
    Sale,
    StockTransfer,
    StockTransferItem,
    Store,
    Supplier,
    User,
)
from .plans import PLANS, is_writable, plan_of, refresh_company_status
from .schemas import (
    CustomerPatch,
    ShiftCloseIn,
    ShiftOpenIn,
    StoreIn,
    SupplierIn,
    TransferCreate,
)
from .security import client_host, create_platform_token, create_token, decode_token, hash_password, rate_limit

saas_router = APIRouter(prefix="/api", tags=["saas"])
platform_router = APIRouter(prefix="/api/platform", tags=["platform"])


def _company(db: Session, user: User) -> Company:
    company = db.get(Company, user.company_id)
    if not company:
        raise HTTPException(400, "Kompaniya topilmadi")
    refresh_company_status(company)
    return company


def _writable(db: Session, user: User) -> Company:
    company = _company(db, user)
    if not is_writable(company):
        raise HTTPException(402, "Obuna tugagan yoki to'xtatilgan. Billing orqali to'lang.")
    return company


def _store_count(db: Session, company_id: int) -> int:
    return db.query(Store).filter(Store.company_id == company_id, Store.is_active.is_(True)).count()


def _user_count(db: Session, company_id: int) -> int:
    return db.query(User).filter(User.company_id == company_id, User.is_active.is_(True)).count()


def _store_user(db: Session, store: Store) -> User | None:
    return (
        db.query(User)
        .filter(
            User.role == "STORE",
            User.store_id == store.id,
            User.company_id == store.company_id,
        )
        .first()
    )


def _upsert_store_login(db: Session, company_id: int, store: Store, username, password, *, require_password=False):
    username = (username or "").strip().lower()
    existing = _store_user(db, store)
    if not username and not existing:
        return None
    if not username:
        return existing
    taken = db.query(User).filter(User.username == username)
    if existing:
        taken = taken.filter(User.id != existing.id)
    if taken.first():
        raise HTTPException(409, "Bu login band")
    pw = password or ""
    if existing:
        existing.username = username
        existing.full_name = store.name
        existing.store_id = store.id
        existing.company_id = company_id
        if pw:
            if len(pw) < 6:
                raise HTTPException(400, "Parol kamida 6 belgi")
            existing.password_hash = hash_password(pw)
        return existing
    if require_password or len(pw) < 6:
        if len(pw) < 6:
            raise HTTPException(400, "Parol kamida 6 belgi")
    user = User(
        company_id=company_id,
        store_id=store.id,
        full_name=store.name,
        username=username,
        password_hash=hash_password(pw),
        role="STORE",
        is_active=True,
    )
    db.add(user)
    return user


def require_platform(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Platform token kerak")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except ValueError:
        raise HTTPException(401, "Invalid token")
    if payload.get("role") != "PLATFORM":
        raise HTTPException(403, "Platform ruxsati yo'q")
    return payload


@saas_router.get("/stores")
def list_stores(user: User = Depends(require_perm("stores")), db: Session = Depends(get_db)):
    rows = db.query(Store).filter(Store.company_id == user.company_id).order_by(Store.id).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "address": s.address,
            "phone": s.phone,
            "is_active": bool(s.is_active),
            "current": s.id == user.store_id,
            "username": (su.username if (su := _store_user(db, s)) else ""),
        }
        for s in rows
    ]


@saas_router.post("/stores")
def create_store(body: StoreIn, user: User = Depends(require_perm("stores")), db: Session = Depends(get_db)):
    company = _writable(db, user)
    limits = plan_of(company.plan if company.status == "ACTIVE" else "FREE")
    if _store_count(db, company.id) >= limits["stores"]:
        raise HTTPException(402, f"Tarif limiti: {limits['stores']} do'kon. Tarifni yangilang.")
    store = Store(
        company_id=company.id,
        name=body.name.strip(),
        address=body.address or "",
        phone=body.phone or "",
        is_active=True,
    )
    db.add(store)
    write_audit(db, user, "store.create", entity="store", payload={"name": store.name})
    db.commit()
    db.refresh(store)
    uname = (body.username or "").strip()
    su = _upsert_store_login(
        db, company.id, store, body.username, body.password, require_password=bool(uname)
    )
    db.commit()
    return {"id": store.id, "name": store.name, "username": su.username if su else ""}


@saas_router.patch("/stores/{store_id}")
def patch_store(
    store_id: int,
    body: StoreIn,
    user: User = Depends(require_perm("stores")),
    db: Session = Depends(get_db),
):
    store = db.get(Store, store_id)
    if not store or store.company_id != user.company_id:
        raise HTTPException(404, "Do'kon topilmadi")
    if body.name.strip():
        store.name = body.name.strip()
    if body.address is not None:
        store.address = body.address
    if body.phone is not None:
        store.phone = body.phone
    su = _upsert_store_login(db, user.company_id, store, body.username, body.password)
    db.commit()
    return {
        "id": store.id,
        "name": store.name,
        "address": store.address,
        "phone": store.phone,
        "username": su.username if su else "",
    }


@saas_router.post("/stores/{store_id}/toggle")
def toggle_store(store_id: int, user: User = Depends(require_perm("stores")), db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store or store.company_id != user.company_id:
        raise HTTPException(404, "Do'kon topilmadi")
    active = db.query(Store).filter(Store.company_id == user.company_id, Store.is_active.is_(True)).count()
    if store.is_active and active <= 1:
        raise HTTPException(400, "Oxirgi do'konni o'chira olmaysiz")
    store.is_active = not store.is_active
    db.commit()
    return {"id": store.id, "is_active": store.is_active}


@saas_router.post("/auth/switch-store")
def switch_store(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "STORE":
        raise HTTPException(403, "Do'kon kabinetidan boshqa do'konga o'tib bo'lmaydi")
    store_id = int(body.get("store_id") or 0)
    store = db.get(Store, store_id)
    if not store or store.company_id != user.company_id or not store.is_active:
        raise HTTPException(404, "Do'kon topilmadi")
    if user.role not in ("OWNER", "ADMIN") and user.store_id != store.id:
        raise HTTPException(403, "Bu do'konga ruxsat yo'q")
    user.store_id = store.id
    db.commit()
    from .routers_auth import user_out
    from .security import create_token

    return {
        "access": create_token(user.id, user.company_id, user.role, user.store_id),
        "user": user_out(db, user).model_dump(),
    }


@saas_router.get("/billing")
def get_billing(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = _company(db, user)
    if company and not company.account_no:
        from .models import next_account_no

        company.account_no = next_account_no(db)
        db.commit()
    plan = (company.plan or "FREE").upper()
    spec = plan_of(plan)
    status = refresh_company_status(company)
    payments = (
        db.query(BillingPayment)
        .filter(BillingPayment.company_id == user.company_id)
        .order_by(BillingPayment.id.desc())
        .limit(24)
        .all()
    )
    db.commit()
    return {
        "account_id": company.account_no,
        "balance": 0.0,
        "plan": plan,
        "status": status,
        "writable": is_writable(company),
        "trial_ends_at": company.trial_ends_at.isoformat() if company.trial_ends_at else None,
        "expires_at": (company.paid_until or company.trial_ends_at).isoformat()
        if (company.paid_until or company.trial_ends_at)
        else None,
        "limits": {"stores": spec["stores"], "users": spec["users"], "price": spec["price"]},
        "usage": {"stores": _store_count(db, company.id), "users": _user_count(db, company.id)},
        "plans": {k: {"price": v["price"], "stores": v["stores"], "users": v["users"]} for k, v in PLANS.items()},
        "currency": company.currency,
        "vat_percent": company.vat_percent,
        "payments": [
            {
                "n": p.id,
                "at": (p.paid_at or p.created_at).isoformat() if (p.paid_at or p.created_at) else "",
                "period": p.period,
                "amount": p.amount,
                "method": p.method,
                "status": p.status,
            }
            for p in payments
        ],
    }


@saas_router.post("/billing/checkout")
def billing_checkout(body: dict, user: User = Depends(require_perm("billing")), db: Session = Depends(get_db)):
    _writable  # billing itself allowed even if past due
    company = _company(db, user)
    plan = str(body.get("plan") or "PRO").upper()
    method = str(body.get("method") or "click").lower()
    if plan not in PLANS or plan == "FREE":
        raise HTTPException(400, "Tarif noto'g'ri")
    spec = plan_of(plan)
    pay = BillingPayment(
        company_id=company.id,
        amount=spec["price"],
        plan=plan,
        method=method,
        status="pending",
        period=datetime.utcnow().strftime("%Y-%m"),
        provider_ref=f"inv-{company.id}-{int(datetime.utcnow().timestamp())}",
    )
    db.add(pay)
    db.commit()
    db.refresh(pay)
    base = settings.app_url.rstrip("/")
    demo = f"{base}/api/billing/demo-pay/{pay.id}"
    if method == "click" and settings.click_service_id and settings.click_merchant_id:
        url = (
            "https://my.click.uz/services/pay"
            f"?service_id={settings.click_service_id}&merchant_id={settings.click_merchant_id}"
            f"&amount={spec['price']}&transaction_param={pay.provider_ref}&return_url={demo}"
        )
    elif method == "payme" and settings.payme_merchant_id:
        url = f"{settings.payme_checkout_url}/{pay.provider_ref}"
    else:
        url = demo
    return {"ok": True, "payment_id": pay.id, "amount": spec["price"], "url": url, "demo": url == demo}


@saas_router.get("/billing/demo-pay/{payment_id}")
def billing_demo_page(payment_id: int, db: Session = Depends(get_db)):
    pay = db.get(BillingPayment, payment_id)
    if not pay:
        raise HTTPException(404, "To'lov topilmadi")
    return {
        "ok": True,
        "message": "Demo to'lov. Productionda Click/Payme ishlatiladi.",
        "payment_id": pay.id,
        "amount": pay.amount,
        "plan": pay.plan,
        "status": pay.status,
        "confirm": f"/api/billing/demo-pay/{pay.id}/confirm",
    }


@saas_router.post("/billing/demo-pay/{payment_id}/confirm")
def billing_demo_confirm(
    payment_id: int,
    user: User = Depends(require_perm("billing")),
    db: Session = Depends(get_db),
):
    pay = db.get(BillingPayment, payment_id)
    if not pay or pay.company_id != user.company_id:
        raise HTTPException(404, "To'lov topilmadi")
    return _activate_payment(db, payment_id, method="demo", user=user)


def _activate_payment(db: Session, payment_id: int, method: str = "", user: User | None = None) -> dict:
    pay = db.get(BillingPayment, payment_id)
    if not pay:
        raise HTTPException(404, "To'lov topilmadi")
    if pay.status == "paid":
        return {"ok": True, "already": True}
    company = db.get(Company, pay.company_id)
    now = datetime.utcnow()
    start = company.paid_until if company.paid_until and company.paid_until > now else now
    company.plan = pay.plan
    company.paid_until = start + timedelta(days=30)
    company.status = "ACTIVE"
    pay.status = "paid"
    pay.method = method or pay.method
    pay.paid_at = now
    write_audit(
        db,
        user,
        "billing.activate",
        entity="billing_payment",
        entity_id=pay.id,
        company_id=pay.company_id,
        payload={"plan": pay.plan, "method": method or pay.method},
    )
    db.commit()
    return {"ok": True, "plan": company.plan, "paid_until": company.paid_until.isoformat()}


def _verify_click_sign(body: dict) -> None:
    secret = (settings.click_secret or "").strip()
    if not secret:
        raise HTTPException(503, "Click webhook sozlanmagan")
    sign = str(body.get("sign_string") or body.get("sign") or "").strip().lower()
    if not sign:
        raise HTTPException(403, "Click imzo yo'q")
    raw = (
        f"{body.get('click_trans_id', '')}{body.get('service_id', '')}{secret}"
        f"{body.get('merchant_trans_id', '')}{body.get('amount', '')}"
        f"{body.get('action', '')}{body.get('sign_time', '')}"
    )
    expect = hashlib.md5(raw.encode()).hexdigest()
    if not hmac.compare_digest(expect, sign):
        raise HTTPException(403, "Click imzo noto'g'ri")


def _verify_payme_auth(authorization: str | None) -> None:
    key = (settings.payme_key or "").strip()
    if not key:
        raise HTTPException(503, "Payme webhook sozlanmagan")
    if not authorization:
        raise HTTPException(401, "Payme auth yo'q")
    got = authorization.replace("Basic ", "").strip()
    try:
        decoded = base64.b64decode(got).decode()
    except Exception:
        decoded = ""
    merchant = (settings.payme_merchant_id or "").strip()
    ok = decoded == key or decoded.endswith(":" + key) or (merchant and decoded == f"{merchant}:{key}")
    if not ok:
        raise HTTPException(403, "Payme imzo noto'g'ri")


@saas_router.post("/billing/webhook/click")
def click_webhook(body: dict, db: Session = Depends(get_db)):
    _verify_click_sign(body)
    ref = str(body.get("merchant_trans_id") or body.get("transaction_param") or "")
    pay = db.query(BillingPayment).filter(BillingPayment.provider_ref == ref).first()
    if not pay:
        raise HTTPException(404, "Invoice topilmadi")
    return _activate_payment(db, pay.id, method="click")


@saas_router.post("/billing/webhook/payme")
def payme_webhook(
    body: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    _verify_payme_auth(authorization)
    ref = str(body.get("id") or body.get("account", {}).get("order") or "")
    pay = db.query(BillingPayment).filter(BillingPayment.provider_ref == ref).first()
    if not pay:
        raise HTTPException(404, "Invoice topilmadi")
    return _activate_payment(db, pay.id, method="payme")


@saas_router.get("/shifts/current")
def current_shift(user: User = Depends(require_perm("cash")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    row = (
        db.query(CashShift)
        .filter(CashShift.company_id == user.company_id, CashShift.store_id == store.id, CashShift.status == "OPEN")
        .order_by(CashShift.id.desc())
        .first()
    )
    if not row:
        return {"open": False}
    return {
        "open": True,
        "id": row.id,
        "opening_cash": row.opening_cash,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "user_id": row.user_id,
    }


@saas_router.post("/shifts/open")
def open_shift(body: ShiftOpenIn, user: User = Depends(require_perm("cash")), db: Session = Depends(get_db)):
    _writable(db, user)
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    exists = (
        db.query(CashShift)
        .filter(CashShift.company_id == user.company_id, CashShift.store_id == store.id, CashShift.status == "OPEN")
        .first()
    )
    if exists:
        raise HTTPException(400, "Smena allaqachon ochiq")
    row = CashShift(
        company_id=user.company_id,
        store_id=store.id,
        user_id=user.id,
        opening_cash=body.opening_cash,
        note=body.note or "",
        status="OPEN",
    )
    db.add(row)
    write_audit(db, user, "shift.open", entity="shift", payload={"opening_cash": body.opening_cash})
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@saas_router.post("/shifts/close")
def close_shift(body: ShiftCloseIn, user: User = Depends(require_perm("cash")), db: Session = Depends(get_db)):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    row = (
        db.query(CashShift)
        .filter(CashShift.company_id == user.company_id, CashShift.store_id == store.id, CashShift.status == "OPEN")
        .order_by(CashShift.id.desc())
        .first()
    )
    if not row:
        raise HTTPException(400, "Ochiq smena yo'q")
    cash = 0.0
    for t in db.query(CashTxn).filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id):
        cash += t.amount if t.kind in ("SALE", "IN") else -t.amount
    row.closing_cash = body.closing_cash
    row.expected_cash = round(cash, 2)
    row.status = "CLOSED"
    row.closed_at = datetime.utcnow()
    row.note = (row.note + " " + (body.note or "")).strip()
    write_audit(db, user, "shift.close", entity="shift", entity_id=row.id, payload={"closing": body.closing_cash})
    db.commit()
    return {"ok": True, "expected_cash": row.expected_cash, "closing_cash": row.closing_cash}


@saas_router.get("/suppliers")
def list_suppliers(user: User = Depends(require_perm("suppliers")), db: Session = Depends(get_db)):
    rows = db.query(Supplier).filter(Supplier.company_id == user.company_id).order_by(Supplier.name).all()
    return [{"id": s.id, "name": s.name, "phone": s.phone, "note": s.note, "is_active": s.is_active} for s in rows]


@saas_router.post("/suppliers")
def create_supplier(body: SupplierIn, user: User = Depends(require_perm("suppliers")), db: Session = Depends(get_db)):
    _writable(db, user)
    s = Supplier(company_id=user.company_id, name=body.name.strip(), phone=body.phone or "", note=body.note or "")
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "phone": s.phone}


@saas_router.patch("/suppliers/{supplier_id}")
def patch_supplier(
    supplier_id: int,
    body: SupplierIn,
    user: User = Depends(require_perm("suppliers")),
    db: Session = Depends(get_db),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != user.company_id:
        raise HTTPException(404, "Yetkazuvchi topilmadi")
    s.name = body.name.strip() or s.name
    s.phone = body.phone or ""
    s.note = body.note or ""
    db.commit()
    return {"id": s.id, "name": s.name}


@saas_router.post("/transfers")
def create_transfer(body: TransferCreate, user: User = Depends(require_perm("stock")), db: Session = Depends(get_db)):
    _writable(db, user)
    forbid_company_kirim_write(user)
    if user.role == "STORE" and body.from_store_id != user.store_id:
        raise HTTPException(403, "Faqat o'z do'koningizdan o'tkazma qilishingiz mumkin")
    src = db.get(Store, body.from_store_id)
    dst = db.get(Store, body.to_store_id)
    if not src or not dst or src.company_id != user.company_id or dst.company_id != user.company_id:
        raise HTTPException(400, "Do'kon noto'g'ri")
    if src.id == dst.id:
        raise HTTPException(400, "Bir xil do'kon")
    if not body.items:
        raise HTTPException(400, "Qatorlar yo'q")
    count = db.query(StockTransfer).filter(StockTransfer.company_id == user.company_id).count() + 1
    doc = StockTransfer(
        company_id=user.company_id,
        from_store_id=src.id,
        to_store_id=dst.id,
        number=f"TR-{count:06d}",
        note=body.note or "",
        status="DONE",
    )
    db.add(doc)
    db.flush()
    for row in body.items:
        product = db.get(Product, row.product_id)
        if not product or product.company_id != user.company_id or product.store_id != src.id:
            raise HTTPException(404, "Mahsulot topilmadi")
        dest = (
            db.query(Product)
            .filter(Product.company_id == user.company_id, Product.store_id == dst.id, Product.barcode == product.barcode)
            .first()
        )
        if not dest:
            dest = Product(
                company_id=user.company_id,
                store_id=dst.id,
                category_id=product.category_id,
                name=product.name,
                sku=product.sku,
                barcode=product.barcode,
                unit=product.unit,
                buy_price=product.buy_price,
                sell_price=product.sell_price,
                stock=0,
                min_stock=product.min_stock,
                manufacturer=product.manufacturer,
                vat_rate=product.vat_rate,
                is_active=True,
            )
            db.add(dest)
            db.flush()
        move_stock(db, product, -row.qty, user=user, store_id=src.id, kind="TRANSFER_OUT", ref_type="transfer", ref_id=doc.id)
        move_stock(db, dest, row.qty, user=user, store_id=dst.id, kind="TRANSFER_IN", ref_type="transfer", ref_id=doc.id)
        db.add(StockTransferItem(transfer_id=doc.id, product_id=product.id, dest_product_id=dest.id, qty=row.qty))
    write_audit(db, user, "transfer.create", entity="transfer", entity_id=doc.id)
    db.commit()
    return {"id": doc.id, "number": doc.number}


@saas_router.get("/transfers")
def list_transfers(user: User = Depends(require_perm("stock")), db: Session = Depends(get_db)):
    rows = (
        db.query(StockTransfer)
        .filter(StockTransfer.company_id == user.company_id)
        .order_by(StockTransfer.id.desc())
        .limit(50)
        .all()
    )
    names = {s.id: s.name for s in db.query(Store).filter(Store.company_id == user.company_id)}
    return [
        {
            "id": t.id,
            "number": t.number,
            "from_store": names.get(t.from_store_id, ""),
            "to_store": names.get(t.to_store_id, ""),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@saas_router.get("/customers/{customer_id}")
def get_customer(customer_id: int, user: User = Depends(require_perm("customers")), db: Session = Depends(get_db)):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != user.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    ledger = (
        db.query(CustomerLedger)
        .filter(CustomerLedger.customer_id == c.id)
        .order_by(CustomerLedger.id.desc())
        .limit(80)
        .all()
    )
    sales = (
        db.query(Sale)
        .filter(Sale.customer_id == c.id, Sale.company_id == user.company_id)
        .order_by(Sale.id.desc())
        .limit(40)
        .all()
    )
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "note": c.note,
        "debt": c.debt,
        "credit_limit": c.credit_limit,
        "is_active": c.is_active,
        "ledger": [
            {
                "id": x.id,
                "kind": x.kind,
                "amount": x.amount,
                "note": x.note,
                "created_at": x.created_at.isoformat() if x.created_at else None,
            }
            for x in ledger
        ],
        "sales": [
            {"id": s.id, "number": s.number, "total": s.total, "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in sales
        ],
    }


@saas_router.patch("/customers/{customer_id}")
def patch_customer(
    customer_id: int,
    body: CustomerPatch,
    user: User = Depends(require_perm("customers")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != user.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    if body.name is not None and body.name.strip():
        c.name = body.name.strip()
    if body.phone is not None:
        c.phone = body.phone
    if body.email is not None:
        c.email = body.email
    if body.note is not None:
        c.note = body.note
    if body.credit_limit is not None:
        c.credit_limit = body.credit_limit
    db.commit()
    return {"id": c.id, "name": c.name, "phone": c.phone, "debt": c.debt, "credit_limit": c.credit_limit}


def _iso(dt):
    return dt.isoformat() if dt else None


def _owner_of(db: Session, company_id: int) -> User | None:
    return (
        db.query(User)
        .filter(User.company_id == company_id, User.role == "OWNER")
        .order_by(User.id)
        .first()
    )


def _company_card(db: Session, c: Company) -> dict:
    refresh_company_status(c)
    owner = _owner_of(db, c.id)
    return {
        "id": c.id,
        "name": c.name,
        "plan": c.plan,
        "status": c.status,
        "account_no": c.account_no,
        "phone": c.phone or "",
        "trial_ends_at": _iso(c.trial_ends_at),
        "paid_until": _iso(c.paid_until),
        "created_at": _iso(c.created_at),
        "stores": _store_count(db, c.id),
        "users": _user_count(db, c.id),
        "owner_name": owner.full_name if owner else "",
        "owner_username": owner.username if owner else "",
        "notes": (getattr(c, "notes", None) or "")[:120],
    }


def _gen_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


@platform_router.post("/login")
def platform_login(body: dict, request: Request):
    rate_limit("plat:" + client_host(request), 8, 60)
    login = str(body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    if login != settings.platform_owner_login.strip().lower() or password != settings.platform_owner_password:
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    return {
        "access": create_platform_token(),
        "user": {"role": "PLATFORM", "username": login, "full_name": "Platform owner"},
    }


@platform_router.get("/me")
def platform_me(payload: dict = Depends(require_platform)):
    return {
        "role": "PLATFORM",
        "username": settings.platform_owner_login,
        "full_name": "Platform owner",
    }


@platform_router.get("/overview")
def platform_overview(_: dict = Depends(require_platform), db: Session = Depends(get_db)):
    rows = db.query(Company).all()
    now = datetime.utcnow()
    trial = active = past_due = suspended = ending = 0
    mrr = 0.0
    for c in rows:
        st = refresh_company_status(c)
        if st == "TRIAL":
            trial += 1
            if c.trial_ends_at and now <= c.trial_ends_at <= now + timedelta(days=7):
                ending += 1
        elif st == "ACTIVE":
            active += 1
            mrr += float(plan_of(c.plan).get("price") or 0)
        elif st == "PAST_DUE":
            past_due += 1
        elif st == "SUSPENDED":
            suspended += 1
    db.commit()
    from .models import AuditLog

    audit = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(16).all()
    return {
        "companies": len(rows),
        "trial": trial,
        "active": active,
        "past_due": past_due,
        "suspended": suspended,
        "trial_ending_7d": ending,
        "users": db.query(User).filter(User.is_active.is_(True)).count(),
        "stores": db.query(Store).filter(Store.is_active.is_(True)).count(),
        "mrr": mrr,
        "currency": "UZS",
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "entity": a.entity,
                "entity_id": a.entity_id,
                "company_id": a.company_id,
                "created_at": _iso(a.created_at),
            }
            for a in audit
        ],
    }


@platform_router.get("/companies")
def platform_companies(
    q: str = "",
    status: str = "",
    plan: str = "",
    limit: int = 50,
    offset: int = 0,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    query = db.query(Company)
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        clauses = [Company.name.ilike(like), Company.phone.ilike(like)]
        if term.isdigit():
            clauses.append(Company.id == int(term))
            clauses.append(Company.account_no == int(term))
        query = query.filter(or_(*clauses))
    pl = (plan or "").strip().upper()
    if pl:
        query = query.filter(Company.plan == pl)
    st = (status or "").strip().upper()
    rows = query.order_by(Company.id.desc()).all()
    cards = [_company_card(db, c) for c in rows]
    if st:
        cards = [x for x in cards if x["status"] == st]
    total = len(cards)
    lim = min(max(limit, 1), 200)
    off = max(0, offset)
    db.commit()
    return {"total": total, "items": cards[off : off + lim]}


@platform_router.post("/companies")
def platform_create_company(
    body: dict,
    request: Request,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    rate_limit("plat-create:" + client_host(request), 10, 60)
    name = str(body.get("name") or "").strip()
    username = str(body.get("username") or "").strip().lower()
    full_name = str(body.get("full_name") or "Owner").strip()
    store_name = str(body.get("store_name") or "Asosiy do'kon").strip()
    if not name or not username:
        raise HTTPException(400, "Kompaniya nomi va login shart")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Bu login band")
    password = str(body.get("password") or "")
    generated = False
    if len(password) < 6:
        password = _gen_password()
        generated = True
    plan = str(body.get("plan") or "FREE").upper()
    if plan not in PLANS:
        plan = "FREE"
    now = datetime.utcnow()
    from .models import next_account_no
    from .routers_auth import seed_catalog

    company = Company(
        name=name,
        plan=plan,
        status="TRIAL" if plan == "FREE" else "ACTIVE",
        account_no=next_account_no(db),
        trial_ends_at=now + timedelta(days=int(body.get("trial_days") or 30)),
        paid_until=(now + timedelta(days=30)) if plan != "FREE" else None,
        currency="UZS",
        locale="uz",
        country="UZ",
        notes=str(body.get("notes") or ""),
    )
    db.add(company)
    db.flush()
    store = Store(company_id=company.id, name=store_name or "Asosiy do'kon")
    db.add(store)
    db.flush()
    user = User(
        company_id=company.id,
        store_id=store.id,
        full_name=full_name,
        username=username,
        password_hash=hash_password(password),
        role="OWNER",
    )
    db.add(user)
    seed_catalog(db, company.id, store.id)
    write_audit(db, None, "platform.company.create", entity="company", entity_id=company.id, company_id=company.id)
    db.commit()
    db.refresh(company)
    out = _company_card(db, company)
    out["password"] = password if generated or body.get("return_password") else None
    out["username"] = username
    return out


@platform_router.get("/companies/{company_id}")
def platform_company_detail(company_id: int, _: dict = Depends(require_platform), db: Session = Depends(get_db)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Kompaniya topilmadi")
    refresh_company_status(c)
    owner = _owner_of(db, c.id)
    users = db.query(User).filter(User.company_id == c.id).order_by(User.id).all()
    stores = db.query(Store).filter(Store.company_id == c.id).order_by(Store.id).all()
    pays = (
        db.query(BillingPayment)
        .filter(BillingPayment.company_id == c.id)
        .order_by(BillingPayment.id.desc())
        .limit(24)
        .all()
    )
    from .models import AuditLog

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == c.id)
        .order_by(AuditLog.id.desc())
        .limit(40)
        .all()
    )
    db.commit()
    spec = plan_of(c.plan)
    return {
        **_company_card(db, c),
        "address": c.address or "",
        "inn": c.inn or "",
        "currency": c.currency,
        "notes": getattr(c, "notes", None) or "",
        "writable": is_writable(c),
        "limits": {"stores": spec["stores"], "users": spec["users"], "price": spec["price"]},
        "owner": None
        if not owner
        else {
            "id": owner.id,
            "full_name": owner.full_name,
            "username": owner.username,
            "is_active": bool(owner.is_active),
        },
        "staff": [
            {
                "id": u.id,
                "full_name": u.full_name,
                "username": u.username,
                "role": u.role,
                "is_active": bool(u.is_active),
            }
            for u in users
        ],
        "store_rows": [
            {"id": s.id, "name": s.name, "phone": s.phone, "address": s.address, "is_active": bool(s.is_active)}
            for s in stores
        ],
        "payments": [
            {
                "id": p.id,
                "amount": p.amount,
                "plan": p.plan,
                "method": p.method,
                "status": p.status,
                "period": p.period,
                "created_at": _iso(p.created_at),
                "paid_at": _iso(p.paid_at),
            }
            for p in pays
        ],
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "entity": a.entity,
                "entity_id": a.entity_id,
                "created_at": _iso(a.created_at),
                "payload": a.payload,
            }
            for a in audit
        ],
    }


@platform_router.patch("/companies/{company_id}")
def platform_patch_company(
    company_id: int,
    body: dict,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Kompaniya topilmadi")
    if body.get("plan"):
        plan = str(body["plan"]).upper()
        if plan not in PLANS:
            raise HTTPException(400, "Tarif noto'g'ri")
        c.plan = plan
    if "notes" in body:
        c.notes = str(body.get("notes") or "")[:4000]
    if body.get("status"):
        st = str(body["status"]).upper()
        if st == "SUSPENDED":
            c.status = "SUSPENDED"
        elif st in ("ACTIVE", "TRIAL", "UNSUSPEND"):
            if (c.status or "").upper() == "SUSPENDED":
                c.status = "ACTIVE"
            refresh_company_status(c)
        else:
            raise HTTPException(400, "Holat noto'g'ri")
    if body.get("paid_until"):
        c.paid_until = datetime.fromisoformat(str(body["paid_until"])[:19])
        c.status = "ACTIVE"
    if body.get("extend_days"):
        now = datetime.utcnow()
        start = c.paid_until if c.paid_until and c.paid_until > now else now
        c.paid_until = start + timedelta(days=int(body["extend_days"]))
        c.status = "ACTIVE"
    write_audit(
        db,
        None,
        "platform.company.patch",
        entity="company",
        entity_id=c.id,
        company_id=c.id,
        payload={k: body.get(k) for k in ("plan", "status", "extend_days", "notes") if k in body},
    )
    db.commit()
    return _company_card(db, c)


@platform_router.post("/companies/{company_id}/impersonate")
def platform_impersonate(
    company_id: int,
    request: Request,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    rate_limit("plat-imp:" + client_host(request), 12, 60)
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Kompaniya topilmadi")
    owner = _owner_of(db, c.id)
    if not owner or not owner.is_active:
        raise HTTPException(400, "Faol owner topilmadi")
    from .routers_auth import user_out

    write_audit(db, owner, "platform.impersonate", entity="company", entity_id=c.id, company_id=c.id)
    db.commit()
    data = user_out(db, owner)
    payload = data.model_dump()
    payload["impersonated"] = True
    return {"access": create_token(owner.id, owner.company_id, owner.role, owner.store_id), "user": payload}


@platform_router.post("/companies/{company_id}/reset-password")
def platform_reset_password(
    company_id: int,
    body: dict,
    request: Request,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    rate_limit("plat-rst:" + client_host(request), 8, 60)
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Kompaniya topilmadi")
    owner = _owner_of(db, c.id)
    if not owner:
        raise HTTPException(400, "Owner topilmadi")
    password = str(body.get("password") or "").strip()
    if len(password) < 6:
        raise HTTPException(400, "Yangi parol kamida 6 belgi")
    owner.password_hash = hash_password(password)
    write_audit(db, owner, "platform.password.reset", entity="user", entity_id=owner.id, company_id=c.id)
    db.commit()
    return {"ok": True, "username": owner.username}


@platform_router.get("/audit")
def platform_audit(
    company_id: int | None = None,
    limit: int = 50,
    _: dict = Depends(require_platform),
    db: Session = Depends(get_db),
):
    from .models import AuditLog

    query = db.query(AuditLog)
    if company_id:
        query = query.filter(AuditLog.company_id == company_id)
    rows = query.order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 200)).all()
    return [
        {
            "id": a.id,
            "action": a.action,
            "entity": a.entity,
            "entity_id": a.entity_id,
            "company_id": a.company_id,
            "user_id": a.user_id,
            "payload": a.payload,
            "created_at": _iso(a.created_at),
        }
        for a in rows
    ]
