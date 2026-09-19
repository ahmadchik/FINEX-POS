from collections import defaultdict
from datetime import datetime, timedelta

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
import os
from fastapi.responses import Response
from .report_xlsx import content_disposition, export_filename, fill_hisobot_xlsx
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import write_audit
from .db import get_db
from .deps import current_store, forbid_company_kirim_write, require_perm
from .ledger import move_stock
from .models import CashTxn, Expense, Product, Sale, SaleItem, StockIn, StockInItem, StockMovement, StockOpname, StockOpnameLine, Store, User
from .plans import plan_of, refresh_company_status
from .schemas import CashCreate, StaffIn, StaffPatch, StockAdjustIn, StockInCreate, StockOpnameCreate, StockOpnameLineIn, StockOpnameLinePatch
from .security import ROLES, hash_password

router = APIRouter(prefix="/api", tags=["ops"])

TEMPLATE_XLSX = os.path.normpath(os.path.join(os.path.dirname(__file__), "web", "assets", "docs", "Finex_Hisobot_template.xlsx"))


@router.post("/stock-ins")
def create_stock_in(
    body: StockInCreate,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    if not body.items:
        raise HTTPException(400, "Qatorlar yo'q")
    store = current_store(user, db)
    count = db.query(StockIn).filter(StockIn.company_id == user.company_id).count() + 1
    doc = StockIn(
        company_id=user.company_id,
        store_id=store.id,
        number=f"IN-{count:06d}",
        supplier=body.supplier,
        note=body.note,
    )
    db.add(doc)
    db.flush()
    total = 0.0
    for row in body.items:
        try:
            qty = float(row.qty)
        except (TypeError, ValueError):
            raise HTTPException(400, "Miqdor noto'g'ri")
        if qty != qty or qty <= 0:
            raise HTTPException(400, "Miqdor 0 dan katta bo'lsin")
        qty = round(qty, 3)
        product = db.get(Product, row.product_id)
        if not product or product.company_id != user.company_id or product.store_id != store.id:
            raise HTTPException(404, "Mahsulot topilmadi")
        if not product.is_active:
            raise HTTPException(400, "Mahsulot nofaol")
        move_stock(db, product, qty, user=user, store_id=store.id, kind="IN", ref_type="stock_in", ref_id=doc.id)
        if row.buy_price:
            product.buy_price = row.buy_price
        line = qty * (row.buy_price or product.buy_price)
        total += line
        db.add(StockInItem(stock_in_id=doc.id, product_id=product.id, qty=qty, buy_price=row.buy_price))
    doc.total = round(total, 2)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "number": doc.number, "total": doc.total}


@router.get("/stock-ins")
def list_stock_ins(user: User = Depends(require_perm("stock")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    rows = (
        db.query(StockIn)
        .filter(StockIn.company_id == user.company_id, StockIn.store_id == store.id)
        .order_by(StockIn.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": d.id,
            "number": d.number,
            "supplier": d.supplier,
            "total": d.total,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.get("/stock-ins/{doc_id}")
def get_stock_in(doc_id: int, user: User = Depends(require_perm("stock")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    doc = db.get(StockIn, doc_id)
    if not doc or doc.company_id != user.company_id or doc.store_id != store.id:
        raise HTTPException(404, "Hujjat topilmadi")
    return {
        "id": doc.id,
        "number": doc.number,
        "supplier": doc.supplier,
        "note": doc.note,
        "total": doc.total,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "items": [
            {
                "product_id": i.product_id,
                "name": i.product.name if i.product else "",
                "qty": i.qty,
                "buy_price": i.buy_price,
            }
            for i in doc.items
        ],
    }



MOVEMENT_LIST_DEFAULT = 50
MOVEMENT_LIST_MAX = 200
MOVEMENT_KINDS = (
    "OPENING",
    "IN",
    "SALE",
    "RETURN",
    "TRANSFER_OUT",
    "TRANSFER_IN",
    "ADJUST",
)


def _parse_movement_dt(value: str | None, *, end: bool = False):
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        if len(raw) <= 10:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            if end:
                return dt + timedelta(days=1)
            return dt
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(400, "Sana noto'g'ri")


@router.get("/stock-movements")
def list_stock_movements(
    response: Response,
    product_id: int | None = None,
    kind: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(MOVEMENT_LIST_DEFAULT, ge=1),
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    store = current_store(user, db)
    limit = min(int(limit), MOVEMENT_LIST_MAX)
    page = max(int(page), 1)
    offset = (page - 1) * limit
    q = db.query(StockMovement).filter(
        StockMovement.company_id == user.company_id,
        StockMovement.store_id == store.id,
    )
    if product_id is not None:
        product = db.get(Product, product_id)
        if not product or product.company_id != user.company_id or product.store_id != store.id:
            raise HTTPException(404, "Mahsulot topilmadi")
        q = q.filter(StockMovement.product_id == product_id)
    kind_n = (kind or "").strip().upper()
    if kind_n:
        q = q.filter(StockMovement.kind == kind_n)
    start = _parse_movement_dt(date_from, end=False)
    end = _parse_movement_dt(date_to, end=True)
    if start is not None:
        q = q.filter(StockMovement.created_at >= start)
    if end is not None:
        q = q.filter(StockMovement.created_at < end)
    total = q.count()
    rows = (
        q.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    product_ids = {m.product_id for m in rows}
    user_ids = {m.user_id for m in rows if m.user_id}
    products = {
        p.id: p
        for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    users = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Limit"] = str(limit)
    out = []
    for m in rows:
        p = products.get(m.product_id)
        u = users.get(m.user_id) if m.user_id else None
        out.append(
            {
                "id": m.id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "product_id": m.product_id,
                "product_name": p.name if p else "",
                "sku": (p.sku or "") if p else "",
                "barcode": (p.barcode or "") if p else "",
                "kind": m.kind,
                "qty": m.qty,
                "balance_after": m.balance_after,
                "user_id": m.user_id,
                "user_name": u.full_name if u else "",
                "store_id": m.store_id,
                "note": m.note or "",
                "ref_type": m.ref_type or "",
                "ref_id": m.ref_id,
            }
        )
    return out



@router.post("/stock-adjustments")
def create_stock_adjustment(
    body: StockAdjustIn,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    """Difference-based adjust: new_stock = current + qty. Maps to move_stock(kind=ADJUST)."""
    store = current_store(user, db)
    try:
        qty = float(body.qty)
    except (TypeError, ValueError):
        raise HTTPException(400, "Miqdor noto'g'ri")
    if qty != qty:
        raise HTTPException(400, "Miqdor noto'g'ri")
    qty = round(qty, 3)
    if abs(qty) < 0.0001:
        raise HTTPException(400, "Tuzatish noldan farq qilsin")
    reason = (body.reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "Sabab kamida 3 belgi")
    product = db.get(Product, body.product_id)
    if not product or product.company_id != user.company_id or product.store_id != store.id:
        raise HTTPException(404, "Mahsulot topilmadi")
    if not product.is_active:
        raise HTTPException(400, "Mahsulot nofaol")
    before = float(product.stock or 0)
    after = round(before + qty, 3)
    if after < -0.0001:
        raise HTTPException(400, f"{product.name}: qoldiq yetarli emas ({product.stock})")
    move_stock(
        db,
        product,
        qty,
        user=user,
        store_id=store.id,
        kind="ADJUST",
        note=reason[:300],
        ref_type="stock_adjust",
        ref_id=product.id,
    )
    write_audit(
        db,
        user,
        "stock.adjust",
        entity="product",
        entity_id=product.id,
        payload={
            "store_id": store.id,
            "product_id": product.id,
            "qty": qty,
            "stock_before": before,
            "stock_after": float(product.stock or 0),
            "reason": reason[:300],
        },
    )
    db.commit()
    db.refresh(product)
    mov = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.kind == "ADJUST",
            StockMovement.store_id == store.id,
        )
        .order_by(StockMovement.id.desc())
        .first()
    )

    return {
        "product_id": product.id,
        "stock_before": before,
        "qty": qty,
        "stock_after": float(product.stock or 0),
        "reason": reason,
        "kind": "ADJUST",
        "movement_id": mov.id if mov else None,
    }


OPNAME_LIST_DEFAULT = 50
OPNAME_LIST_MAX = 200
OPNAME_OPEN_CONFLICT = "Bu do'konda ochiq inventarizatsiya bor"
OPNAME_LINE_CONFLICT = "Bu mahsulot allaqachon qo'shilgan"
OPNAME_READONLY = "Faqat ochiq inventarizatsiya o'zgartiriladi"
OPNAME_COUNTED_REQUIRED = "Barcha qatorlarda sanangan miqdor bo'lsin"
OPNAME_COUNTED_NEGATIVE = "Sanangan miqdor manfiy bo'lmasin"


def _get_store_opname(db: Session, user: User, store: Store, opname_id: int) -> StockOpname:
    doc = db.get(StockOpname, opname_id)
    if not doc or doc.company_id != user.company_id or doc.store_id != store.id:
        raise HTTPException(404, "Hujjat topilmadi")
    return doc


def _require_opname_open(doc: StockOpname) -> None:
    if (doc.status or "").upper() != "OPEN":
        raise HTTPException(409, OPNAME_READONLY)


def _opname_header(doc: StockOpname, *, store_name: str = "", created_by_name: str = "", line_count: int | None = None) -> dict:
    out = {
        "id": doc.id,
        "number": doc.number,
        "status": doc.status,
        "store_id": doc.store_id,
        "store_name": store_name,
        "note": doc.note or "",
        "created_by": doc.created_by,
        "created_by_name": created_by_name,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "posted_at": doc.posted_at.isoformat() if doc.posted_at else None,
        "cancelled_at": doc.cancelled_at.isoformat() if doc.cancelled_at else None,
    }
    if line_count is not None:
        out["line_count"] = line_count
    return out


@router.post("/stock-opnames")
def create_stock_opname(
    body: StockOpnameCreate,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    existing = (
        db.query(StockOpname)
        .filter(
            StockOpname.company_id == user.company_id,
            StockOpname.store_id == store.id,
            StockOpname.status == "OPEN",
        )
        .first()
    )
    if existing:
        raise HTTPException(409, OPNAME_OPEN_CONFLICT)
    count = db.query(StockOpname).filter(StockOpname.company_id == user.company_id).count() + 1
    doc = StockOpname(
        company_id=user.company_id,
        store_id=store.id,
        number=f"OP-{count:06d}",
        status="OPEN",
        note=(body.note or "")[:300],
        created_by=user.id,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, OPNAME_OPEN_CONFLICT)
    write_audit(
        db,
        user,
        "stock.opname.create",
        entity="stock_opname",
        entity_id=doc.id,
        payload={
            "opname_id": doc.id,
            "number": doc.number,
            "company_id": user.company_id,
            "store_id": store.id,
            "user_id": user.id,
        },
    )
    db.commit()
    db.refresh(doc)
    return _opname_header(doc, store_name=store.name, created_by_name=user.full_name, line_count=0)


@router.get("/stock-opnames")
def list_stock_opnames(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(OPNAME_LIST_DEFAULT, ge=1),
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    limit = min(int(limit), OPNAME_LIST_MAX)
    page = max(int(page), 1)
    offset = (page - 1) * limit
    q = db.query(StockOpname).filter(
        StockOpname.company_id == user.company_id,
        StockOpname.store_id == store.id,
    )
    total = q.count()
    rows = q.order_by(StockOpname.created_at.desc(), StockOpname.id.desc()).offset(offset).limit(limit).all()
    ids = [d.id for d in rows]
    line_counts = {}
    if ids:
        for oid, n in (
            db.query(StockOpnameLine.opname_id, func.count(StockOpnameLine.id))
            .filter(StockOpnameLine.opname_id.in_(ids))
            .group_by(StockOpnameLine.opname_id)
            .all()
        ):
            line_counts[oid] = int(n)
    user_ids = {d.created_by for d in rows if d.created_by}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Limit"] = str(limit)
    return [
        _opname_header(
            d,
            store_name=store.name,
            created_by_name=(users[d.created_by].full_name if d.created_by and d.created_by in users else ""),
            line_count=line_counts.get(d.id, 0),
        )
        for d in rows
    ]


@router.get("/stock-opnames/{opname_id}")
def get_stock_opname(
    opname_id: int,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    store = current_store(user, db)
    doc = _get_store_opname(db, user, store, opname_id)
    lines = (
        db.query(StockOpnameLine)
        .filter(StockOpnameLine.opname_id == doc.id)
        .order_by(StockOpnameLine.id)
        .all()
    )
    product_ids = {ln.product_id for ln in lines}
    products = {
        p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    creator = db.get(User, doc.created_by) if doc.created_by else None
    header = _opname_header(
        doc,
        store_name=store.name,
        created_by_name=creator.full_name if creator else "",
        line_count=len(lines),
    )
    header["lines"] = []
    for ln in lines:
        p = products.get(ln.product_id)
        header["lines"].append(
            {
                "id": ln.id,
                "line_id": ln.id,
                "product_id": ln.product_id,
                "product_name": p.name if p else "",
                "sku": (p.sku or "") if p else "",
                "barcode": (p.barcode or "") if p else "",
                "is_active": bool(p.is_active) if p else None,
                "system_qty": ln.system_qty,
                "counted_qty": ln.counted_qty,
                "difference": ln.difference,
            }
        )
    return header


@router.post("/stock-opnames/{opname_id}/lines")
def add_stock_opname_line(
    opname_id: int,
    body: StockOpnameLineIn,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    doc = _get_store_opname(db, user, store, opname_id)
    _require_opname_open(doc)
    product = db.get(Product, body.product_id)
    if not product or product.company_id != user.company_id or product.store_id != store.id:
        raise HTTPException(404, "Mahsulot topilmadi")
    if not product.is_active:
        raise HTTPException(400, "Mahsulot nofaol")
    line = StockOpnameLine(
        opname_id=doc.id,
        product_id=product.id,
        system_qty=float(product.stock or 0),
        counted_qty=body.counted_qty,
        difference=None,
    )
    db.add(line)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, OPNAME_LINE_CONFLICT)
    db.commit()
    db.refresh(line)
    return {
        "id": line.id,
        "line_id": line.id,
        "product_id": line.product_id,
        "product_name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "is_active": bool(product.is_active),
        "system_qty": line.system_qty,
        "counted_qty": line.counted_qty,
        "difference": line.difference,
    }


@router.patch("/stock-opnames/{opname_id}/lines/{line_id}")
def patch_stock_opname_line(
    opname_id: int,
    line_id: int,
    body: StockOpnameLinePatch,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    doc = _get_store_opname(db, user, store, opname_id)
    _require_opname_open(doc)
    line = db.get(StockOpnameLine, line_id)
    if not line or line.opname_id != doc.id:
        raise HTTPException(404, "Qator topilmadi")
    line.counted_qty = body.counted_qty
    # difference is stored at finalize (Step 6D), not here
    line.difference = None
    db.commit()
    db.refresh(line)
    return {
        "id": line.id,
        "line_id": line.id,
        "product_id": line.product_id,
        "system_qty": line.system_qty,
        "counted_qty": line.counted_qty,
        "difference": line.difference,
    }


@router.delete("/stock-opnames/{opname_id}/lines/{line_id}")
def delete_stock_opname_line(
    opname_id: int,
    line_id: int,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    doc = _get_store_opname(db, user, store, opname_id)
    _require_opname_open(doc)
    line = db.get(StockOpnameLine, line_id)
    if not line or line.opname_id != doc.id:
        raise HTTPException(404, "Qator topilmadi")
    db.delete(line)
    db.commit()
    return {"ok": True}



@router.post("/stock-opnames/{opname_id}/finalize")
def finalize_stock_opname(
    opname_id: int,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
    """Atomic OPEN -> POSTED reconciliation via move_stock(kind=ADJUST)."""
    forbid_company_kirim_write(user)
    store = current_store(user, db)
    doc = _get_store_opname(db, user, store, opname_id)
    status = (doc.status or "").upper()
    if status != "OPEN":
        raise HTTPException(409, OPNAME_READONLY)
    lines = (
        db.query(StockOpnameLine)
        .filter(StockOpnameLine.opname_id == doc.id)
        .order_by(StockOpnameLine.id)
        .all()
    )
    for line in lines:
        if line.counted_qty is None:
            raise HTTPException(400, OPNAME_COUNTED_REQUIRED)
        counted = float(line.counted_qty)
        if counted != counted:
            raise HTTPException(400, OPNAME_COUNTED_REQUIRED)
        if counted < 0:
            raise HTTPException(400, OPNAME_COUNTED_NEGATIVE)
    raw_note = (doc.note or "").strip()
    mv_note = (f"{doc.number} · {raw_note}" if raw_note else (doc.number or "opname"))[:300]
    total_adj = 0.0
    adjusted = 0
    try:
        for line in lines:
            product = db.get(Product, line.product_id)
            if not product or product.company_id != user.company_id or product.store_id != store.id:
                raise HTTPException(404, "Mahsulot topilmadi")
            db.refresh(product)
            counted = float(line.counted_qty)
            system_qty = float(line.system_qty or 0)
            diff = round(counted - system_qty, 3)
            live = float(product.stock or 0)
            if live + diff < -0.0001:
                raise HTTPException(400, f"{product.name}: qoldiq yetarli emas ({product.stock})")
            line.difference = diff
            if abs(diff) >= 0.0001:
                move_stock(
                    db,
                    product,
                    diff,
                    user=user,
                    store_id=store.id,
                    kind="ADJUST",
                    note=mv_note,
                    ref_type="opname",
                    ref_id=doc.id,
                )
                adjusted += 1
                total_adj += diff
        doc.status = "POSTED"
        doc.posted_at = datetime.now()
        write_audit(
            db,
            user,
            "stock.opname.finalize",
            entity="stock_opname",
            entity_id=doc.id,
            payload={
                "opname_id": doc.id,
                "number": doc.number,
                "company_id": user.company_id,
                "store_id": store.id,
                "line_count": len(lines),
                "adjusted": adjusted,
                "total_adjustment": round(total_adj, 3),
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    db.refresh(doc)
    return _opname_header(doc, store_name=store.name, created_by_name=user.full_name, line_count=len(lines))


@router.get("/cash")
def cash_state(user: User = Depends(require_perm("cash")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    txns = (
        db.query(CashTxn)
        .filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id)
        .order_by(CashTxn.id.desc())
        .limit(120)
        .all()
    )
    balance = 0.0
    all_tx = db.query(CashTxn).filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id).all()
    for t in all_tx:
        if t.kind in ("SALE", "IN"):
            balance += t.amount
        else:
            balance -= t.amount
    card = (
        db.query(func.coalesce(func.sum(Sale.paid_card), 0))
        .filter(
            Sale.company_id == user.company_id,
            Sale.store_id == store.id,
            Sale.status != "RETURNED",
        )
        .scalar()
    )
    sale_ids = [t.sale_id for t in txns if t.sale_id]
    numbers = {}
    if sale_ids:
        for s in db.query(Sale).filter(Sale.id.in_(sale_ids)).all():
            numbers[s.id] = s.number
    return {
        "balance": round(balance, 2),
        "cash": round(balance, 2),
        "card": round(float(card or 0), 2),
        "txns": [
            {
                "id": t.id,
                "kind": t.kind,
                "amount": t.amount,
                "note": t.note,
                "sale_id": t.sale_id,
                "sale_number": numbers.get(t.sale_id) if t.sale_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ],
    }


@router.post("/cash")
def add_cash(
    body: CashCreate,
    user: User = Depends(require_perm("cash")),
    db: Session = Depends(get_db),
):
    forbid_company_kirim_write(user)
    kind = (body.kind or "").upper()
    if kind not in ("IN", "OUT"):
        raise HTTPException(400, "Kirim yoki Chiqim tanlang")
    if body.amount <= 0:
        raise HTTPException(400, "Summa majburiy")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "Izoh majburiy")
    store = current_store(user, db)
    if kind == "OUT":
        bal = 0.0
        for t in db.query(CashTxn).filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id):
            bal += t.amount if t.kind in ("SALE", "IN") else -t.amount
        if body.amount > bal + 0.01:
            raise HTTPException(400, "Kassada yetarli naqd yo'q")
    txn = CashTxn(
        company_id=user.company_id,
        store_id=store.id,
        kind=kind,
        amount=body.amount,
        note=note,
    )
    db.add(txn)
    db.commit()
    return {"ok": True, "id": txn.id}


@router.get("/reports/dashboard")
def dashboard(user: User = Depends(require_perm("reports")), db: Session = Depends(get_db)):
    store = current_store(user, db)
    now = datetime.now()
    today = now.date()
    start = datetime(today.year, today.month, today.day)
    week_start = start - timedelta(days=6)
    month_start = datetime(today.year, today.month, 1)

    def sale_filter(since: datetime):
        return (
            Sale.company_id == user.company_id,
            Sale.store_id == store.id,
            Sale.created_at >= since,
            Sale.status != "RETURNED",
        )

    def agg(since: datetime):
        q = db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.tax_total), 0),
        ).filter(*sale_filter(since))
        total, count, tax = q.first()
        sold = (
            db.query(func.coalesce(func.sum(SaleItem.qty), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .filter(*sale_filter(since))
            .scalar()
        )
        # Foyda = savdo (chegirmadan keyin) − tannarx. Tannarx chek yozilgan paytdagi buy_price.
        profit_rows = (
            db.query(Sale, SaleItem, Product)
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
            .filter(*sale_filter(since))
            .all()
        )
        totals = {}
        cogs = {}
        for sale, item, product in profit_rows:
            unit_cost = item.buy_price if item.buy_price is not None else (product.buy_price or 0)
            cogs[sale.id] = cogs.get(sale.id, 0.0) + float(unit_cost or 0) * float(item.qty or 0)
            totals[sale.id] = float(sale.total or 0)
        profit = sum(totals[sid] - cogs[sid] for sid in totals)
        return {
            "sales": round(float(total or 0), 2),
            "tax": round(float(tax or 0), 2),
            "checks": int(count or 0),
            "sold_qty": float(sold or 0),
            "profit": round(float(profit or 0), 2),
        }

    cash = 0.0
    for t in db.query(CashTxn).filter(CashTxn.company_id == user.company_id, CashTxn.store_id == store.id):
        cash += t.amount if t.kind in ("SALE", "IN") else -t.amount

    low = (
        db.query(Product)
        .filter(
            Product.company_id == user.company_id,
            Product.store_id == store.id,
            Product.is_active.is_(True),
            Product.min_stock > 0,
            Product.stock <= Product.min_stock,
        )
        .order_by(Product.stock.asc())
        .limit(8)
        .all()
    )
    top = (
        db.query(SaleItem.name, func.sum(SaleItem.qty).label("qty"))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.company_id == user.company_id, Sale.store_id == store.id, Sale.created_at >= week_start, Sale.status != "RETURNED")
        .group_by(SaleItem.name)
        .order_by(func.sum(SaleItem.qty).desc())
        .limit(5)
        .all()
    )
    return {
        "today": agg(start),
        "week": agg(week_start),
        "month": agg(month_start),
        "cash": round(cash, 2),
        "low_stock": [{"id": p.id, "name": p.name, "stock": p.stock, "min_stock": p.min_stock} for p in low],
        "top_products": [{"name": n, "qty": float(q)} for n, q in top],
    }



def _xml_text(value):
    text = "".join(ch for ch in str(value or "") if ord(ch) >= 32 or ch in "\t\n")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _col_letter(idx):
    n = idx
    out = ""
    while True:
        out = chr(65 + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            break
    return out


def _xlsx_bytes(headers, rows):
    def cell(ref, value):
        if isinstance(value, (int, float)) and value == value:
            return f'<c r="{ref}" t="n"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(value)}</t></is></c>'

    body_rows = []
    for r_idx, row in enumerate([headers] + rows, 1):
        cells = "".join(cell(f"{_col_letter(c)}{r_idx}", v) for c, v in enumerate(row))
        body_rows.append(f'<row r="{r_idx}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body_rows)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Hisobot" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    ctypes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ctypes)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()



def _turnover_rows(user, db, store, start, end):
    products = (
        db.query(Product)
        .filter(Product.company_id == user.company_id, Product.store_id == store.id)
        .all()
    )
    by_id = {p.id: p for p in products}
    ins = defaultdict(lambda: {"before": 0.0, "period": 0.0, "after": 0.0, "period_sum": 0.0})
    outs = defaultdict(lambda: {"before": 0.0, "period": 0.0, "after": 0.0, "period_sum": 0.0})
    names = {}
    units = {}
    prices = {}

    for p in products:
        names[p.id] = p.name
        units[p.id] = p.unit or "dona"
        prices[p.id] = float(p.buy_price or 0) or float(p.sell_price or 0)

    kirim_q = (
        db.query(StockInItem, StockIn, Product)
        .join(StockIn, StockInItem.stock_in_id == StockIn.id)
        .join(Product, StockInItem.product_id == Product.id)
        .filter(StockIn.company_id == user.company_id, StockIn.store_id == store.id)
        .all()
    )
    for item, doc, product in kirim_q:
        pid = item.product_id
        qty = float(item.qty or 0)
        price = float(item.buy_price or 0) or float(product.buy_price or 0) or prices.get(pid, 0)
        names[pid] = product.name if product else names.get(pid, "Tovar")
        units[pid] = (product.unit if product else None) or units.get(pid, "dona")
        if price:
            prices[pid] = price
        at = doc.created_at
        rec = ins[pid]
        if at is None or at < start:
            rec["before"] += qty
        elif at < end:
            rec["period"] += qty
            rec["period_sum"] += qty * price
        else:
            rec["after"] += qty

    sales_q = (
        db.query(SaleItem, Sale)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.company_id == user.company_id,
            Sale.store_id == store.id,
            Sale.status != "RETURNED",
        )
        .all()
    )
    for item, sale in sales_q:
        pid = item.product_id
        qty = float(item.qty or 0)
        cost = float(item.buy_price or 0) or prices.get(pid, 0)
        names[pid] = item.name or names.get(pid, "Tovar")
        if pid in by_id:
            units[pid] = by_id[pid].unit or units.get(pid, "dona")
            if not cost:
                cost = float(by_id[pid].buy_price or 0) or float(by_id[pid].sell_price or 0)
        prices[pid] = prices.get(pid, 0) or cost
        rec = outs[pid]
        at = sale.created_at
        if at is None or at < start:
            rec["before"] += qty
        elif at < end:
            rec["period"] += qty
            rec["period_sum"] += qty * cost
        else:
            rec["after"] += qty

    rows = []
    opening_stock = 0.0
    ids = sorted(set(by_id) | set(ins) | set(outs), key=lambda i: (names.get(i) or "").lower())
    n = 0
    for pid in ids:
        p = by_id.get(pid)
        stock = float(p.stock or 0) if p else 0.0
        price = float(prices.get(pid) or 0)
        in_qty = ins[pid]["period"]
        out_qty = outs[pid]["period"]
        close_qty = stock - ins[pid]["after"] + outs[pid]["after"]
        open_qty = close_qty - in_qty + out_qty
        open_sum = round(open_qty * price, 2)
        in_sum = round(ins[pid]["period_sum"] or (in_qty * price), 2)
        out_sum = round(outs[pid]["period_sum"] or (out_qty * price), 2)
        close_sum = round(close_qty * price, 2)
        if not any([open_qty, in_qty, out_qty, close_qty, stock]):
            continue
        n += 1
        opening_stock += open_sum
        rows.append({
            "n": n,
            "name": names.get(pid) or (p.name if p else "Tovar"),
            "unit": units.get(pid) or "dona",
            "price": round(price, 2),
            "open_qty": round(open_qty, 3),
            "open_sum": open_sum,
            "in_qty": round(in_qty, 3),
            "in_sum": in_sum,
            "out_qty": round(out_qty, 3),
            "out_sum": out_sum,
            "close_qty": round(close_qty, 3),
            "close_sum": close_sum,
        })
    return rows, round(opening_stock, 2)


def _reports_data(user, db, date_from, date_to, op_type):
    store = current_store(user, db)
    start = datetime.fromisoformat(date_from.strip()[:10]) if date_from.strip() else datetime(1970, 1, 1)
    end = datetime.fromisoformat(date_to.strip()[:10]) + timedelta(days=1) if date_to.strip() else datetime(2100, 1, 1)
    op = (op_type or "all").lower()

    kirim_q = (
        db.query(StockInItem, StockIn, Product)
        .join(StockIn, StockInItem.stock_in_id == StockIn.id)
        .join(Product, StockInItem.product_id == Product.id)
        .filter(
            StockIn.company_id == user.company_id,
            StockIn.store_id == store.id,
            StockIn.created_at >= start,
            StockIn.created_at < end,
        )
        .all()
    )
    chiqim_sales = (
        db.query(SaleItem, Sale)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.company_id == user.company_id,
            Sale.store_id == store.id,
            Sale.status != "RETURNED",
            Sale.created_at >= start,
            Sale.created_at < end,
        )
        .all()
    )
    expenses = (
        db.query(Expense)
        .filter(
            Expense.company_id == user.company_id,
            Expense.store_id == store.id,
            Expense.created_at >= start,
            Expense.created_at < end,
        )
        .all()
    )

    rows = []
    chart_map = {}

    def bump(day, kirim=0.0, chiqim=0.0):
        rec = chart_map.setdefault(day, {"kirim": 0.0, "chiqim": 0.0})
        rec["kirim"] += kirim
        rec["chiqim"] += chiqim

    kirim_total = 0.0
    for item, doc, product in kirim_q:
        price = float(item.buy_price or 0) or float(product.buy_price or 0)
        amount = float(item.qty or 0) * price
        kirim_total += amount
        day = doc.created_at.date().isoformat() if doc.created_at else ""
        bump(day, kirim=amount)
        rows.append({
            "at": doc.created_at.isoformat() if doc.created_at else "",
            "day": day,
            "type": "kirim",
            "title": product.name if product else (doc.number or "Kirim"),
            "qty": float(item.qty or 0),
            "amount": round(amount, 2),
            "ref": doc.number,
        })

    chiqim_total = 0.0
    for item, sale in chiqim_sales:
        amount = float(item.line_total or 0)
        chiqim_total += amount
        day = sale.created_at.date().isoformat() if sale.created_at else ""
        bump(day, chiqim=amount)
        rows.append({
            "at": sale.created_at.isoformat() if sale.created_at else "",
            "day": day,
            "type": "chiqim",
            "title": item.name,
            "qty": float(item.qty or 0),
            "amount": round(amount, 2),
            "ref": sale.number,
        })
    for exp in expenses:
        amount = float(exp.amount or 0)
        chiqim_total += amount
        day = exp.created_at.date().isoformat() if exp.created_at else ""
        bump(day, chiqim=amount)
        rows.append({
            "at": exp.created_at.isoformat() if exp.created_at else "",
            "day": day,
            "type": "chiqim",
            "title": exp.category or "Xarajat",
            "qty": 1,
            "amount": round(amount, 2),
            "ref": "Xarajat",
        })

    if op == "kirim":
        rows = [r for r in rows if r["type"] == "kirim"]
    elif op == "chiqim":
        rows = [r for r in rows if r["type"] == "chiqim"]

    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    days = sorted(chart_map.keys())
    stock_value = 0.0
    for p in db.query(Product).filter(
        Product.company_id == user.company_id,
        Product.store_id == store.id,
        Product.is_active.is_(True),
    ):
        stock_value += float(p.stock or 0) * float(p.buy_price or 0)

    turnover, opening_stock = _turnover_rows(user, db, store, start, end)
    period_from = date_from.strip()[:10] if date_from.strip() else ""
    period_to = date_to.strip()[:10] if date_to.strip() else ""
    return {
        "kirim": round(kirim_total, 2),
        "chiqim": round(chiqim_total, 2),
        "stock_value": round(stock_value, 2),
        "opening_stock": opening_stock,
        "store_name": store.name if store else "",
        "date_from": period_from,
        "date_to": period_to,
        "chart": {
            "labels": days,
            "kirim": [round(chart_map[d]["kirim"], 2) for d in days],
            "chiqim": [round(chart_map[d]["chiqim"], 2) for d in days],
        },
        "rows": rows,
        "turnover": turnover,
    }


@router.get("/reports/analytics")
def reports_analytics(
    date_from: str = "",
    date_to: str = "",
    op_type: str = "all",
    user: User = Depends(require_perm("reports")),
    db: Session = Depends(get_db),
):
    return _reports_data(user, db, date_from, date_to, op_type)


@router.get("/reports/export")
def reports_export(
    date_from: str = "",
    date_to: str = "",
    op_type: str = "all",
    report_no: str = "00001",
    user: User = Depends(require_perm("reports")),
    db: Session = Depends(get_db),
):
    data = _reports_data(user, db, date_from, date_to, op_type)
    name = export_filename(date_from, date_to)
    body = fill_hisobot_xlsx(TEMPLATE_XLSX, data, report_no=report_no or "00001")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(name)},
    )


@router.get("/staff")
def list_staff(user: User = Depends(require_perm("staff")), db: Session = Depends(get_db)):
    rows = db.query(User).filter(User.company_id == user.company_id).order_by(User.id).all()
    return [
        {"id": u.id, "full_name": u.full_name, "username": u.username, "role": u.role, "is_active": u.is_active, "store_id": u.store_id}
        for u in rows
    ]


@router.post("/staff")
def create_staff(
    body: StaffIn,
    user: User = Depends(require_perm("staff")),
    db: Session = Depends(get_db),
):
    role = body.role.upper()
    if role == "STORE":
        raise HTTPException(400, "Do'kon loginini Do'konlar modulidan bering")
    if role not in ROLES:
        raise HTTPException(400, "Noto'g'ri rol")
    from .models import Company

    company = db.get(Company, user.company_id)
    refresh_company_status(company)
    spec = plan_of(company.plan if company and company.status == "ACTIVE" else "FREE")
    active_users = db.query(User).filter(User.company_id == user.company_id, User.is_active.is_(True)).count()
    if active_users >= spec["users"]:
        raise HTTPException(402, f"Tarif limiti: {spec['users']} foydalanuvchi")
    username = body.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Bu login band")
    store = current_store(user, db)
    if body.store_id:
        st = db.get(Store, body.store_id)
        if not st or st.company_id != user.company_id:
            raise HTTPException(400, "Do'kon noto'g'ri")
        store = st
    u = User(
        company_id=user.company_id,
        store_id=store.id,
        full_name=body.full_name.strip(),
        username=username,
        password_hash=hash_password(body.password),
        role=role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "username": u.username, "role": u.role}

@router.patch("/staff/{staff_id}")
def update_staff(
    staff_id: int,
    body: StaffPatch,
    user: User = Depends(require_perm("staff")),
    db: Session = Depends(get_db),
):
    u = db.get(User, staff_id)
    if not u or u.company_id != user.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if u.role == "OWNER" and user.id != u.id and user.role != "OWNER":
        raise HTTPException(403, "Egasi tahrirlanmaydi")
    if body.full_name and body.full_name.strip():
        u.full_name = body.full_name.strip()
    if body.username and body.username.strip():
        username = body.username.strip().lower()
        other = db.query(User).filter(User.username == username, User.id != u.id).first()
        if other:
            raise HTTPException(409, "Bu login band")
        u.username = username
    if body.password:
        if len(body.password) < 4:
            raise HTTPException(400, "Parol kamida 4 belgi")
        u.password_hash = hash_password(body.password)
    if body.role:
        role = body.role.upper()
        if role not in ROLES or role == "OWNER":
            raise HTTPException(400, "Noto'g'ri rol")
        if u.role == "OWNER":
            raise HTTPException(403, "Egasi roli o'zgarmaydi")
        if u.id == user.id:
            raise HTTPException(400, "O'z rolingizni o'zgartira olmaysiz")
        u.role = role
    if body.store_id:
        st = db.get(Store, body.store_id)
        if not st or st.company_id != user.company_id:
            raise HTTPException(400, "Do'kon noto'g'ri")
        u.store_id = st.id
    db.commit()
    db.refresh(u)
    return {"id": u.id, "username": u.username, "role": u.role, "full_name": u.full_name}


@router.post("/staff/{staff_id}/toggle")
def toggle_staff(
    staff_id: int,
    user: User = Depends(require_perm("staff")),
    db: Session = Depends(get_db),
):
    u = db.get(User, staff_id)
    if not u or u.company_id != user.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if u.id == user.id:
        raise HTTPException(400, "O'zingizni o'chira olmaysiz")
    if u.role == "OWNER":
        raise HTTPException(403, "Do'kon egasi o'chirilmaydi")
    u.is_active = not u.is_active
    db.commit()
    db.refresh(u)
    return {"id": u.id, "is_active": u.is_active}
