"""Phase 2 Step 6A — stock opname tables/models only. No API."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Company, Product, StockOpname, StockOpnameLine, Store, User
from app.security import hash_password


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s, engine
    finally:
        s.close()
        engine.dispose()


def _seed(s, *, company_name="Ahmad Savdo", store_name="A-Dokon", username="op_owner"):
    company = Company(
        name=company_name,
        plan="VIP",
        status="ACTIVE",
        currency="UZS",
        locale="uz",
        vat_percent=12,
        paid_until=datetime.now() + timedelta(days=30),
        trial_ends_at=datetime.now() + timedelta(days=30),
    )
    s.add(company)
    s.flush()
    store = Store(company_id=company.id, name=store_name, is_active=True)
    s.add(store)
    s.flush()
    user = User(
        company_id=company.id,
        store_id=store.id,
        full_name="Ahmad",
        username=username,
        password_hash=hash_password("secret12"),
        role="OWNER",
        is_active=True,
    )
    s.add(user)
    s.flush()
    product = Product(
        company_id=company.id,
        store_id=store.id,
        name="Sut",
        sku="ST-OP",
        barcode="9200000000001",
        unit="dona",
        buy_price=8000,
        sell_price=11200,
        stock=10,
        min_stock=0,
        is_active=True,
    )
    s.add(product)
    s.commit()
    return company, store, user, product


def test_opname_tables_exist(db):
    _s, engine = db
    names = set(inspect(engine).get_table_names())
    assert "stock_opnames" in names
    assert "stock_opname_lines" in names
    cols = {c["name"] for c in inspect(engine).get_columns("stock_opnames")}
    assert cols >= {
        "id",
        "company_id",
        "store_id",
        "number",
        "status",
        "note",
        "created_by",
        "created_at",
        "posted_at",
        "cancelled_at",
    }
    line_cols = {c["name"] for c in inspect(engine).get_columns("stock_opname_lines")}
    assert line_cols >= {"id", "opname_id", "product_id", "system_qty", "counted_qty", "difference"}


def test_opname_company_store_and_null_counted(db):
    s, _engine = db
    company, store, user, product = _seed(s)
    doc = StockOpname(
        company_id=company.id,
        store_id=store.id,
        number="OP-000001",
        status="OPEN",
        note="",
        created_by=user.id,
    )
    s.add(doc)
    s.flush()
    line = StockOpnameLine(
        opname_id=doc.id,
        product_id=product.id,
        system_qty=float(product.stock),
        counted_qty=None,
        difference=None,
    )
    s.add(line)
    s.commit()
    s.refresh(doc)
    s.refresh(line)
    assert doc.company_id == company.id
    assert doc.store_id == store.id
    assert doc.status == "OPEN"
    assert doc.posted_at is None
    assert doc.cancelled_at is None
    assert line.counted_qty is None
    assert line.difference is None
    assert line.system_qty == 10
    assert s.get(Product, product.id).stock == 10


def test_one_open_opname_per_store_db_unique(db):
    s, _engine = db
    company, store, user, _p = _seed(s)
    s.add(StockOpname(company_id=company.id, store_id=store.id, number="OP-000001", status="OPEN", created_by=user.id))
    s.commit()
    s.add(StockOpname(company_id=company.id, store_id=store.id, number="OP-000002", status="OPEN", created_by=user.id))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_posted_and_cancelled_allow_new_open(db):
    s, _engine = db
    company, store, user, _p = _seed(s, username="op_st2")
    a = StockOpname(company_id=company.id, store_id=store.id, number="OP-000001", status="OPEN", created_by=user.id)
    s.add(a)
    s.commit()
    a.status = "POSTED"
    a.posted_at = datetime.now()
    s.commit()
    b = StockOpname(company_id=company.id, store_id=store.id, number="OP-000002", status="OPEN", created_by=user.id)
    s.add(b)
    s.commit()
    b.status = "CANCELLED"
    b.cancelled_at = datetime.now()
    s.commit()
    c = StockOpname(company_id=company.id, store_id=store.id, number="OP-000003", status="OPEN", created_by=user.id)
    s.add(c)
    s.commit()
    opens = s.query(StockOpname).filter(StockOpname.store_id == store.id, StockOpname.status == "OPEN").all()
    assert len(opens) == 1
    assert opens[0].number == "OP-000003"


def test_open_allowed_on_other_store_and_company(db):
    s, _engine = db
    c1, st1, u1, _p1 = _seed(s, username="op_a")
    c2, st2, u2, _p2 = _seed(s, company_name="B Co", store_name="B-Dok", username="op_b")
    st1b = Store(company_id=c1.id, name="A2", is_active=True)
    s.add(st1b)
    s.flush()
    s.add(StockOpname(company_id=c1.id, store_id=st1.id, number="OP-A1", status="OPEN", created_by=u1.id))
    s.add(StockOpname(company_id=c1.id, store_id=st1b.id, number="OP-A2", status="OPEN", created_by=u1.id))
    s.add(StockOpname(company_id=c2.id, store_id=st2.id, number="OP-B1", status="OPEN", created_by=u2.id))
    s.commit()
    assert s.query(StockOpname).filter(StockOpname.status == "OPEN").count() == 3


def test_duplicate_product_line_rejected_two_products_ok(db):
    s, _engine = db
    company, store, user, p1 = _seed(s, username="op_lines")
    p2 = Product(
        company_id=company.id,
        store_id=store.id,
        name="Qatiq",
        sku="ST-OP2",
        barcode="9200000000002",
        unit="dona",
        buy_price=1,
        sell_price=2,
        stock=5,
        is_active=True,
    )
    s.add(p2)
    s.commit()
    doc = StockOpname(company_id=company.id, store_id=store.id, number="OP-000010", status="OPEN", created_by=user.id)
    s.add(doc)
    s.flush()
    s.add(StockOpnameLine(opname_id=doc.id, product_id=p1.id, system_qty=10, counted_qty=None, difference=None))
    s.add(StockOpnameLine(opname_id=doc.id, product_id=p2.id, system_qty=5, counted_qty=None, difference=None))
    s.commit()
    assert s.query(StockOpnameLine).filter(StockOpnameLine.opname_id == doc.id).count() == 2
    s.add(StockOpnameLine(opname_id=doc.id, product_id=p1.id, system_qty=10, counted_qty=9, difference=None))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
    assert s.get(Product, p1.id).stock == 10
    assert s.get(Product, p2.id).stock == 5


def test_ensure_schema_creates_opname_indexes(db):
    _s, engine = db
    rows = engine.connect().execute(
        text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND tbl_name IN ('stock_opnames','stock_opname_lines')"
        )
    ).fetchall()
    names = {r[0] for r in rows if r[0]}
    assert "uq_stock_opnames_company_store_open" in names
    assert "ix_stock_opnames_company_store_created" in names
    assert "uq_stock_opname_lines_opname_product" in names
    assert "ix_stock_opname_lines_opname_id" in names
    open_sql = next(
        (r[1] or "") for r in rows if r[0] == "uq_stock_opnames_company_store_open"
    )
    assert "status" in open_sql and "OPEN" in open_sql
