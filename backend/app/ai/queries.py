"""Read-only POS queries for the AI assistant. Never writes. Tenant scope is server-side."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..deps import current_store
from ..models import Company, Product, Sale, SaleItem, User
from .clock import period_range, snapshot, today_bounds as clock_today_bounds


def _currency(db: Session, user: User) -> str:
    company = db.get(Company, user.company_id)
    return ((company.currency if company else "") or "UZS").upper()


def scoped_store(db: Session, user: User):
    return current_store(user, db)


def parse_iso_date(value, *, field: str) -> datetime:
    raw = str(value or "").strip()[:10]
    if not raw:
        raise ValueError(f"{field} majburiy (YYYY-MM-DD)")
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field} formati YYYY-MM-DD bo'lishi kerak") from exc


def period_bounds(start_date: str, end_date: str) -> tuple[datetime, datetime, str, str]:
    start = parse_iso_date(start_date, field="start_date")
    end_day = parse_iso_date(end_date, field="end_date")
    if end_day < start:
        raise ValueError("end_date start_date dan oldin bo'lmasin")
    until = end_day + timedelta(days=1)
    return start, until, start.date().isoformat(), end_day.date().isoformat()


def today_bounds(db: Session | None = None, user: User | None = None):
    return clock_today_bounds(db, user)


def _sale_filter(user: User, store, since: datetime | None = None, until: datetime | None = None):
    conds = [
        Sale.company_id == user.company_id,
        Sale.store_id == store.id,
        Sale.status != "RETURNED",
    ]
    if since is not None:
        conds.append(Sale.created_at >= since)
    if until is not None:
        conds.append(Sale.created_at < until)
    return tuple(conds)


def _sales_agg(db: Session, user: User, store, since: datetime, until: datetime) -> dict:
    total, count = (
        db.query(func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
        .filter(*_sale_filter(user, store, since, until))
        .first()
    )
    sold = (
        db.query(func.coalesce(func.sum(SaleItem.qty), 0))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(*_sale_filter(user, store, since, until))
        .scalar()
    )
    return {
        "total_sales": round(float(total or 0), 2),
        "transaction_count": int(count or 0),
        "sold_qty": float(sold or 0),
    }


def _profit_amount(db: Session, user: User, store, since: datetime, until: datetime) -> float:
    # Dashboard: sale.total − Σ(item.buy_price × qty); fallback product.buy_price.
    profit_rows = (
        db.query(Sale, SaleItem, Product)
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(*_sale_filter(user, store, since, until))
        .all()
    )
    totals: dict[int, float] = {}
    cogs: dict[int, float] = {}
    for sale, item, product in profit_rows:
        unit_cost = item.buy_price if item.buy_price is not None else (product.buy_price or 0)
        cogs[sale.id] = cogs.get(sale.id, 0.0) + float(unit_cost or 0) * float(item.qty or 0)
        totals[sale.id] = float(sale.total or 0)
    return round(sum(totals[sid] - cogs[sid] for sid in totals), 2)


def get_today_sales(db: Session, user: User) -> dict:
    store = scoped_store(db, user)
    since, until, day = today_bounds(db, user)
    agg = _sales_agg(db, user, store, since, until)
    snap = snapshot(db, user)
    return {
        "date": day,
        "timezone": snap["timezone"],
        "utc_offset": snap["utc_offset"],
        "store_name": store.name,
        "currency": _currency(db, user),
        "total_sales": agg["total_sales"],
        "transaction_count": agg["transaction_count"],
        "sold_qty": agg["sold_qty"],
        "empty": agg["transaction_count"] == 0,
    }


def get_top_selling_products(
    db: Session,
    user: User,
    *,
    limit: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    store = scoped_store(db, user)
    if start_date and end_date:
        since, until, from_s, to_s = period_bounds(start_date, end_date)
    else:
        since, until, to_s = today_bounds(db, user)
        since = since - timedelta(days=6)
        from_s = since.date().isoformat()
    rows = (
        db.query(SaleItem.name, func.sum(SaleItem.qty).label("qty"))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(*_sale_filter(user, store, since, until))
        .group_by(SaleItem.name)
        .order_by(func.sum(SaleItem.qty).desc())
        .limit(limit)
        .all()
    )
    products = [{"name": n, "qty": float(q)} for n, q in rows]
    return {
        "start_date": from_s,
        "end_date": to_s,
        "store_name": store.name,
        "currency": _currency(db, user),
        "limit": limit,
        "products": products,
        "empty": len(products) == 0,
    }


def get_low_stock_products(db: Session, user: User, *, limit: int = 8) -> dict:
    store = scoped_store(db, user)
    rows = (
        db.query(Product)
        .filter(
            Product.company_id == user.company_id,
            Product.store_id == store.id,
            Product.is_active.is_(True),
            Product.min_stock > 0,
            Product.stock <= Product.min_stock,
        )
        .order_by(Product.stock.asc())
        .limit(limit)
        .all()
    )
    items = [
        {"id": p.id, "name": p.name, "stock": float(p.stock or 0), "min_stock": float(p.min_stock or 0), "unit": p.unit or "dona"}
        for p in rows
    ]
    return {
        "store_name": store.name,
        "limit": limit,
        "products": items,
        "empty": len(items) == 0,
    }


def get_inventory_summary(db: Session, user: User) -> dict:
    store = scoped_store(db, user)
    active = (
        db.query(Product)
        .filter(
            Product.company_id == user.company_id,
            Product.store_id == store.id,
            Product.is_active.is_(True),
        )
        .all()
    )
    sku_count = len(active)
    total_qty = round(sum(float(p.stock or 0) for p in active), 3)
    stock_value = round(sum(float(p.stock or 0) * float(p.buy_price or 0) for p in active), 2)
    return {
        "store_name": store.name,
        "currency": _currency(db, user),
        "sku_count": sku_count,
        "total_qty": total_qty,
        "stock_value": stock_value,
        "empty": sku_count == 0,
    }


def get_product_stock(db: Session, user: User, query: str) -> dict:
    store = scoped_store(db, user)
    q = (query or "").strip()
    like = f"%{q}%"
    rows = (
        db.query(Product)
        .filter(
            Product.company_id == user.company_id,
            Product.store_id == store.id,
            (Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)),
        )
        .order_by(Product.name)
        .limit(10)
        .all()
    )
    products = [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku or "",
            "barcode": p.barcode or "",
            "stock": float(p.stock or 0),
            "min_stock": float(p.min_stock or 0),
            "unit": p.unit or "dona",
            "is_active": bool(p.is_active),
        }
        for p in rows
    ]
    return {
        "query": q,
        "store_name": store.name,
        "products": products,
        "empty": len(products) == 0,
    }


def resolve_query_range(db: Session, user: User, period=None, start_date=None, end_date=None) -> tuple[str, str]:
    if period:
        return period_range(db, user, str(period))
    if start_date and end_date:
        return str(start_date).strip()[:10], str(end_date).strip()[:10]
    raise ValueError("period yoki start_date va end_date kerak")


def get_sales_summary(db: Session, user: User, start_date: str | None = None, end_date: str | None = None, period: str | None = None) -> dict:
    store = scoped_store(db, user)
    start_date, end_date = resolve_query_range(db, user, period, start_date, end_date)
    since, until, from_s, to_s = period_bounds(start_date, end_date)
    agg = _sales_agg(db, user, store, since, until)
    return {
        "start_date": from_s,
        "end_date": to_s,
        "period": (period or "").strip().lower() or None,
        "store_name": store.name,
        "currency": _currency(db, user),
        "total_sales": agg["total_sales"],
        "transaction_count": agg["transaction_count"],
        "sold_qty": agg["sold_qty"],
        "empty": agg["transaction_count"] == 0,
    }


def get_profit_summary(db: Session, user: User, start_date: str | None = None, end_date: str | None = None, period: str | None = None) -> dict:
    store = scoped_store(db, user)
    start_date, end_date = resolve_query_range(db, user, period, start_date, end_date)
    since, until, from_s, to_s = period_bounds(start_date, end_date)
    agg = _sales_agg(db, user, store, since, until)
    profit = _profit_amount(db, user, store, since, until)
    return {
        "start_date": from_s,
        "end_date": to_s,
        "period": (period or "").strip().lower() or None,
        "store_name": store.name,
        "currency": _currency(db, user),
        "total_sales": agg["total_sales"],
        "transaction_count": agg["transaction_count"],
        "gross_profit": profit,
        "empty": agg["transaction_count"] == 0,
    }
