from collections import defaultdict
from datetime import datetime, timedelta

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException
import os
from fastapi.responses import Response
from .report_xlsx import content_disposition, export_filename, fill_hisobot_xlsx
from sqlalchemy import func
from sqlalchemy.orm import Session

from .db import get_db
from .deps import current_store, require_perm
from .ledger import move_stock
from .models import CashTxn, Expense, Product, Sale, SaleItem, StockIn, StockInItem, Store, User
from .plans import plan_of, refresh_company_status
from .schemas import CashCreate, StaffIn, StaffPatch, StockInCreate
from .security import ROLES, hash_password

router = APIRouter(prefix="/api", tags=["ops"])

TEMPLATE_XLSX = os.path.normpath(os.path.join(os.path.dirname(__file__), "web", "assets", "docs", "Finex_Hisobot_template.xlsx"))


@router.post("/stock-ins")
def create_stock_in(
    body: StockInCreate,
    user: User = Depends(require_perm("stock")),
    db: Session = Depends(get_db),
):
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
        product = db.get(Product, row.product_id)
        if not product or product.company_id != user.company_id:
            raise HTTPException(404, "Mahsulot topilmadi")
        move_stock(db, product, row.qty, user=user, store_id=store.id, kind="IN", ref_type="stock_in", ref_id=doc.id)
        if row.buy_price:
            product.buy_price = row.buy_price
        line = row.qty * (row.buy_price or product.buy_price)
        total += line
        db.add(StockInItem(stock_in_id=doc.id, product_id=product.id, qty=row.qty, buy_price=row.buy_price))
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
    doc = db.get(StockIn, doc_id)
    if not doc or doc.company_id != user.company_id:
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
        q = db.query(func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id)).filter(*sale_filter(since))
        total, count = q.first()
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
