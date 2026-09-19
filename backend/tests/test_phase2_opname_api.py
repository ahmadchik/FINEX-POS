"""Phase 2 Step 6B — stock opname API (OPEN document only). No finalize, no stock writes."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Product, StockMovement, StockOpname, StockOpnameLine, Company, Store, User
from app.security import _rate, hash_password


@pytest.fixture
def client():
    _rate.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    api = TestClient(app)
    try:
        yield api, Session
    finally:
        app.dependency_overrides.clear()
        _rate.clear()


def _seed_owner(Session, *, username, password="secret12", company_name="Ahmad Savdo"):
    db = Session()
    try:
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
        db.add(company)
        db.flush()
        store = Store(company_id=company.id, name="A-Dokon", is_active=True)
        db.add(store)
        db.flush()
        user = User(
            company_id=company.id,
            store_id=store.id,
            full_name="Ahmad",
            username=username,
            password_hash=hash_password(password),
            role="OWNER",
            is_active=True,
        )
        db.add(user)
        db.commit()
        return {"company_id": company.id, "store_id": store.id, "user_id": user.id}
    finally:
        db.close()


def _login(api, username, password="secret12"):
    res = api.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    data = res.json()
    return {"Authorization": f"Bearer {data['access']}"}, data["user"]


def _product(api, headers, **kw):
    body = {
        "name": "Sut",
        "barcode": "4780001111112",
        "buy_price": 8000,
        "sell_price": 11200,
        "stock": 10,
        **kw,
    }
    res = api.post("/api/products", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _store_headers(api, owner_headers, store_id, username, name="A-Dokon"):
    patched = api.patch(
        f"/api/stores/{store_id}",
        headers=owner_headers,
        json={"name": name, "username": username, "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    return _login(api, username)


def _staff(api, headers, *, username, role, store_id, password="staff12"):
    res = api.post(
        "/api/staff",
        headers=headers,
        json={
            "full_name": role,
            "username": username,
            "password": password,
            "role": role,
            "store_id": store_id,
        },
    )
    assert res.status_code == 200, res.text
    login = api.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access']}"}


def _create_opname(api, headers, note=""):
    return api.post("/api/stock-opnames", headers=headers, json={"note": note})


def _movements(Session, product_id=None):
    db = Session()
    try:
        q = db.query(StockMovement)
        if product_id is not None:
            q = q.filter(StockMovement.product_id == product_id)
        return q.count()
    finally:
        db.close()


def test_create_open_and_hq_forbidden(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_own")
    oh, _u = _login(api, "op_own")
    hq = _create_opname(api, oh, "HQ")
    assert hq.status_code == 403, hq.text
    sh, su = _store_headers(api, oh, seed["store_id"], "op_own_a")
    res = _create_opname(api, sh, "Filial sanash")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "OPEN"
    assert body["number"].startswith("OP-")
    assert body["store_id"] == seed["store_id"]
    assert body["created_by"] == su["id"]
    assert body["line_count"] == 0
    assert body["posted_at"] is None
    assert body["cancelled_at"] is None
    db = Session()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == "stock.opname.create").all()
        assert len(logs) == 1
        assert logs[0].user_id == su["id"]
        assert logs[0].entity == "stock_opname"
        assert logs[0].entity_id == body["id"]
        assert str(seed["store_id"]) in (logs[0].payload or "")
        assert body["number"] in (logs[0].payload or "")
        assert str(seed["company_id"]) in (logs[0].payload or "")
        doc = db.get(StockOpname, body["id"])
        assert doc.status == "OPEN"
        assert doc.company_id == seed["company_id"]
        assert _movements(Session) == 0
    finally:
        db.close()


def test_duplicate_open_409_other_store_ok_posted_allows_new(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_dup")
    oh, _u = _login(api, "op_dup")
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_dup_a")
    a = _create_opname(api, sh)
    assert a.status_code == 200, a.text
    b = _create_opname(api, sh)
    assert b.status_code == 409, b.text

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Dok", "username": "op_dup_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    bh, _bu = _login(api, "op_dup_b")
    other = _create_opname(api, bh)
    assert other.status_code == 200, other.text
    assert other.json()["store_id"] == store_b.json()["id"]

    db = Session()
    try:
        doc = db.get(StockOpname, a.json()["id"])
        doc.status = "POSTED"
        doc.posted_at = datetime.now()
        db.commit()
    finally:
        db.close()
    c = _create_opname(api, sh)
    assert c.status_code == 200, c.text
    db = Session()
    try:
        c2 = db.get(StockOpname, c.json()["id"])
        c2.status = "CANCELLED"
        c2.cancelled_at = datetime.now()
        db.commit()
    finally:
        db.close()
    d = _create_opname(api, sh)
    assert d.status_code == 200, d.text
    listed = api.get("/api/stock-opnames", headers=sh)
    assert listed.status_code == 200
    opens = [x for x in listed.json() if x["status"] == "OPEN"]
    assert len(opens) == 1
    assert opens[0]["id"] == d.json()["id"]


def test_list_and_detail_store_company_isolation(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_iso")
    oh, _u = _login(api, "op_iso")
    p = _product(api, oh, barcode="9300000000001", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_iso_a")
    doc = _create_opname(api, sh).json()
    add = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p["id"]})
    assert add.status_code == 200, add.text

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Iso", "username": "op_iso_b", "password": "secret12"},
    ).json()
    bh, _bu = _login(api, "op_iso_b")
    listed_b = api.get("/api/stock-opnames", headers=bh)
    assert listed_b.status_code == 200
    assert listed_b.json() == []
    foreign = api.get(f"/api/stock-opnames/{doc['id']}", headers=bh)
    assert foreign.status_code == 404

    _seed_owner(Session, username="op_iso_co", company_name="B Co")
    ch, _cu = _login(api, "op_iso_co")
    cross_list = api.get("/api/stock-opnames", headers=ch)
    assert cross_list.status_code == 200
    assert cross_list.json() == []
    cross = api.get(f"/api/stock-opnames/{doc['id']}", headers=ch)
    assert cross.status_code == 404
    # HQ OWNER is forbidden to write, but may read current store
    own_list = api.get("/api/stock-opnames", headers=oh)
    assert own_list.status_code == 200
    assert any(x["id"] == doc["id"] for x in own_list.json())
    assert own_list.json()[0]["line_count"] == 1
    assert "X-Total-Count" in own_list.headers


def test_add_line_snapshot_stays_after_stock_change(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_snap")
    oh, _u = _login(api, "op_snap")
    p = _product(api, oh, barcode="9300000000002", stock=100, sku="ST-OP")
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_snap_a")
    doc = _create_opname(api, sh).json()
    before_mov = _movements(Session, p["id"])
    before_stock = p["stock"]
    line = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p["id"]})
    assert line.status_code == 200, line.text
    assert line.json()["system_qty"] == 100
    assert line.json()["counted_qty"] is None
    assert line.json()["difference"] is None
    assert line.json()["sku"] == "ST-OP"
    db = Session()
    try:
        prod = db.get(Product, p["id"])
        prod.stock = 98
        db.commit()
        assert db.get(Product, p["id"]).stock == 98
    finally:
        db.close()
    detail = api.get(f"/api/stock-opnames/{doc['id']}", headers=sh)
    assert detail.status_code == 200
    rows = detail.json()["lines"]
    assert len(rows) == 1
    assert rows[0]["system_qty"] == 100
    assert rows[0]["counted_qty"] is None
    assert rows[0]["line_id"] == line.json()["line_id"]
    assert _movements(Session, p["id"]) == before_mov
    db = Session()
    try:
        assert db.get(Product, p["id"]).stock == 98
        ln = db.get(StockOpnameLine, line.json()["id"])
        assert ln.system_qty == 100
        assert ln.difference is None
    finally:
        db.close()
    assert before_stock == 100


def test_duplicate_product_409_two_products_ok(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_line")
    oh, _u = _login(api, "op_line")
    p1 = _product(api, oh, barcode="9300000000003", stock=10, sku="A")
    p2 = _product(api, oh, barcode="9300000000004", stock=5, name="Qatiq", sku="B")
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_line_a")
    doc = _create_opname(api, sh).json()
    a = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p1["id"]})
    b = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p2["id"]})
    assert a.status_code == 200 and b.status_code == 200
    dup = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p1["id"]})
    assert dup.status_code == 409
    detail = api.get(f"/api/stock-opnames/{doc['id']}", headers=sh).json()
    assert detail["line_count"] == 2


def test_update_counted_zero_reject_negative_delete(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_qty")
    oh, _u = _login(api, "op_qty")
    p = _product(api, oh, barcode="9300000000005", stock=7)
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_qty_a")
    doc = _create_opname(api, sh).json()
    line = api.post(f"/api/stock-opnames/{doc['id']}/lines", headers=sh, json={"product_id": p["id"]}).json()
    zero = api.patch(
        f"/api/stock-opnames/{doc['id']}/lines/{line['id']}",
        headers=sh,
        json={"counted_qty": 0},
    )
    assert zero.status_code == 200, zero.text
    assert zero.json()["counted_qty"] == 0
    assert zero.json()["difference"] is None
    assert zero.json()["system_qty"] == 7
    neg = api.patch(
        f"/api/stock-opnames/{doc['id']}/lines/{line['id']}",
        headers=sh,
        json={"counted_qty": -1},
    )
    assert neg.status_code in (400, 422)
    bad = api.patch(
        f"/api/stock-opnames/{doc['id']}/lines/{line['id']}",
        headers=sh,
        json={"counted_qty": "abc"},
    )
    assert bad.status_code == 422
    deleted = api.delete(f"/api/stock-opnames/{doc['id']}/lines/{line['id']}", headers=sh)
    assert deleted.status_code == 200
    detail = api.get(f"/api/stock-opnames/{doc['id']}", headers=sh).json()
    assert detail["lines"] == []
    db = Session()
    try:
        assert db.get(Product, p["id"]).stock == 7
        assert db.query(StockOpnameLine).count() == 0
    finally:
        db.close()


def test_posted_and_cancelled_lines_readonly(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_ro")
    oh, _u = _login(api, "op_ro")
    p = _product(api, oh, barcode="9300000000006", stock=3)
    sh, _su = _store_headers(api, oh, seed["store_id"], "op_ro_a")
    posted = _create_opname(api, sh).json()
    line = api.post(f"/api/stock-opnames/{posted['id']}/lines", headers=sh, json={"product_id": p["id"]}).json()
    db = Session()
    try:
        db.get(StockOpname, posted["id"]).status = "POSTED"
        db.commit()
    finally:
        db.close()
    assert api.post(f"/api/stock-opnames/{posted['id']}/lines", headers=sh, json={"product_id": p["id"]}).status_code == 409
    assert api.patch(
        f"/api/stock-opnames/{posted['id']}/lines/{line['id']}",
        headers=sh,
        json={"counted_qty": 1},
    ).status_code == 409
    assert api.delete(f"/api/stock-opnames/{posted['id']}/lines/{line['id']}", headers=sh).status_code == 409

    cancelled = _create_opname(api, sh).json()
    line2 = api.post(f"/api/stock-opnames/{cancelled['id']}/lines", headers=sh, json={"product_id": p["id"]}).json()
    db = Session()
    try:
        db.get(StockOpname, cancelled["id"]).status = "CANCELLED"
        db.commit()
    finally:
        db.close()
    assert api.post(f"/api/stock-opnames/{cancelled['id']}/lines", headers=sh, json={"product_id": p["id"]}).status_code == 409
    assert api.patch(
        f"/api/stock-opnames/{cancelled['id']}/lines/{line2['id']}",
        headers=sh,
        json={"counted_qty": 1},
    ).status_code == 409
    assert api.delete(f"/api/stock-opnames/{cancelled['id']}/lines/{line2['id']}", headers=sh).status_code == 409


def test_cashier_cross_company_product_and_no_stock_writes(client):
    api, Session = client
    seed = _seed_owner(Session, username="op_sec")
    oh, _u = _login(api, "op_sec")
    p = _product(api, oh, barcode="9300000000007", stock=12)
    cash_h = _staff(api, oh, username="op_cash", role="CASHIER", store_id=seed["store_id"])
    assert _create_opname(api, cash_h).status_code == 403

    sh, _su = _store_headers(api, oh, seed["store_id"], "op_sec_a")
    mgr = _staff(api, oh, username="op_mgr", role="MANAGER", store_id=seed["store_id"])
    created = _create_opname(api, mgr)
    assert created.status_code == 200, created.text
    doc_id = created.json()["id"]
    assert api.post(f"/api/stock-opnames/{doc_id}/lines", headers=cash_h, json={"product_id": p["id"]}).status_code == 403

    _seed_owner(Session, username="op_sec_b", company_name="B Co")
    bh, _bu = _login(api, "op_sec_b")
    bp = _product(api, bh, barcode="9300000000008", stock=4)
    cross = api.post(f"/api/stock-opnames/{doc_id}/lines", headers=sh, json={"product_id": bp["id"]})
    assert cross.status_code == 404

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Sec", "username": "op_sec_st", "password": "secret12"},
    )
    assert store_b.status_code == 200
    sth, _stu = _login(api, "op_sec_st")
    assert api.post(f"/api/stock-opnames/{doc_id}/lines", headers=sth, json={"product_id": p["id"]}).status_code == 404
    assert api.get(f"/api/stock-opnames/{doc_id}", headers=sth).status_code == 404

    db = Session()
    try:
        stock = db.get(Product, p["id"]).stock
        movs = db.query(StockMovement).filter(StockMovement.product_id == p["id"]).count()
        opname_refs = (
            db.query(StockMovement)
            .filter(StockMovement.ref_type == "opname")
            .count()
        )
        assert stock == 12
        assert movs == 1  # OPENING only
        assert opname_refs == 0
    finally:
        db.close()

    listed = api.get("/api/stock-opnames", headers=sh)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == doc_id
    wh = _staff(api, oh, username="op_wh", role="WAREHOUSE", store_id=seed["store_id"])
    # WAREHOUSE may write; duplicate OPEN same store -> 409
    assert _create_opname(api, wh).status_code == 409
