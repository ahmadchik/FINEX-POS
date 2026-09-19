"""Phase 2 Step 6F — stock opname cancel (document-only, no stock writes)."""

from datetime import datetime, timedelta
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Product, StockMovement, StockOpname, StockOpnameLine, Company, Store, User
from app.security import _rate, hash_password
import app.routers_ops as ops_mod


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


def _add_line(api, headers, opname_id, product_id, counted=None):
    body = {"product_id": product_id}
    if counted is not None:
        body["counted_qty"] = counted
    res = api.post(f"/api/stock-opnames/{opname_id}/lines", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _cancel(api, headers, opname_id):
    return api.post(f"/api/stock-opnames/{opname_id}/cancel", headers=headers)


def _stock(Session, product_id):
    db = Session()
    try:
        return float(db.get(Product, product_id).stock or 0)
    finally:
        db.close()


def _movements(Session, product_id=None):
    db = Session()
    try:
        q = db.query(StockMovement)
        if product_id is not None:
            q = q.filter(StockMovement.product_id == product_id)
        return q.count()
    finally:
        db.close()


def _adjust_opname(Session, opname_id):
    db = Session()
    try:
        return (
            db.query(StockMovement)
            .filter(StockMovement.kind == "ADJUST", StockMovement.ref_type == "opname", StockMovement.ref_id == opname_id)
            .count()
        )
    finally:
        db.close()


def _audit(Session, action="stock.opname.cancel"):
    db = Session()
    try:
        return db.query(AuditLog).filter(AuditLog.action == action).all()
    finally:
        db.close()


def test_cancel_open_to_cancelled(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_a")
    oh, _u = _login(api, "cn_a")
    p = _product(api, oh, barcode="9500000000001", stock=10)
    sh, su = _store_headers(api, oh, seed["store_id"], "cn_a_st")
    doc = _create_opname(api, sh, "Bekor").json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=7)
    before_stock = _stock(Session, p["id"])
    before_mov = _movements(Session, p["id"])
    res = _cancel(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == doc["id"]
    assert body["number"] == doc["number"]
    assert body["status"] == "CANCELLED"
    assert body["cancelled_at"]
    assert body["posted_at"] is None
    assert body["line_count"] == 1
    assert _stock(Session, p["id"]) == before_stock == 10
    assert _movements(Session, p["id"]) == before_mov
    assert _adjust_opname(Session, doc["id"]) == 0
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "CANCELLED"
        assert op.cancelled_at is not None
        assert op.posted_at is None
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.system_qty == 10
        assert ln.counted_qty == 7
        assert ln.difference is None
        assert db.query(StockOpnameLine).filter(StockOpnameLine.opname_id == doc["id"]).count() == 1
    finally:
        db.close()
    logs = _audit(Session)
    assert len(logs) == 1
    assert logs[0].user_id == su["id"]
    assert logs[0].entity == "stock_opname"
    assert logs[0].entity_id == doc["id"]
    payload = json.loads(logs[0].payload or "{}")
    assert payload["opname_id"] == doc["id"]
    assert payload["number"] == doc["number"]
    assert payload["line_count"] == 1
    got = api.get(f"/api/stock-opnames/{doc['id']}", headers=sh)
    assert got.status_code == 200
    assert got.json()["status"] == "CANCELLED"
    assert got.json()["lines"][0]["counted_qty"] == 7
    assert got.json()["lines"][0]["difference"] is None


def test_cancel_repeated_409(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_h")
    oh, _u = _login(api, "cn_h")
    p = _product(api, oh, barcode="9500000000002", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_h_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    first = _cancel(api, sh, doc["id"])
    assert first.status_code == 200, first.text
    stock = _stock(Session, p["id"])
    mov = _movements(Session, p["id"])
    audits = len(_audit(Session))
    second = _cancel(api, sh, doc["id"])
    assert second.status_code == 409, second.text
    assert _stock(Session, p["id"]) == stock
    assert _movements(Session, p["id"]) == mov
    assert len(_audit(Session)) == audits
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "CANCELLED"
    finally:
        db.close()


def test_cancel_posted_409(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_i")
    oh, _u = _login(api, "cn_i")
    p = _product(api, oh, barcode="9500000000003", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_i_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=10)
    fin = api.post(f"/api/stock-opnames/{doc['id']}/finalize", headers=sh)
    assert fin.status_code == 200, fin.text
    stock = _stock(Session, p["id"])
    mov = _movements(Session, p["id"])
    res = _cancel(api, sh, doc["id"])
    assert res.status_code == 409, res.text
    assert _stock(Session, p["id"]) == stock
    assert _movements(Session, p["id"]) == mov
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "POSTED"
        assert op.cancelled_at is None
        assert op.posted_at is not None
    finally:
        db.close()
    assert _audit(Session) == []


def test_cancel_foreign_company_404(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_j")
    oh, _u = _login(api, "cn_j")
    p = _product(api, oh, barcode="9500000000004", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_j_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    seed_b = _seed_owner(Session, username="cn_j_co", company_name="B Co")
    oh2, _u2 = _login(api, "cn_j_co")
    bh, _bu = _store_headers(api, oh2, seed_b["store_id"], "cn_j_b")
    res = _cancel(api, bh, doc["id"])
    assert res.status_code == 404, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
        assert db.get(StockOpname, doc["id"]).cancelled_at is None
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _audit(Session) == []


def test_cancel_foreign_store_404(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_k")
    oh, _u = _login(api, "cn_k")
    p = _product(api, oh, barcode="9500000000005", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_k_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Cn", "username": "cn_k_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    bh, _bu = _login(api, "cn_k_b")
    res = _cancel(api, bh, doc["id"])
    assert res.status_code == 404, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _audit(Session) == []


def test_cancel_cashier_403(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_l")
    oh, _u = _login(api, "cn_l")
    p = _product(api, oh, barcode="9500000000006", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_l_st")
    cash = _staff(api, oh, username="cn_l_csh", role="CASHIER", store_id=seed["store_id"])
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    res = _cancel(api, cash, doc["id"])
    assert res.status_code == 403, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _audit(Session) == []


def test_cancel_hq_owner_admin_403(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_m")
    oh, _u = _login(api, "cn_m")
    p = _product(api, oh, barcode="9500000000007", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_m_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    hq = _cancel(api, oh, doc["id"])
    assert hq.status_code == 403, hq.text
    adm = _staff(api, oh, username="cn_m_adm", role="ADMIN", store_id=seed["store_id"])
    admin_res = _cancel(api, adm, doc["id"])
    assert admin_res.status_code == 403, admin_res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
        assert db.get(StockOpname, doc["id"]).cancelled_at is None
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _audit(Session) == []


def test_cancel_failed_no_success_audit(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_n")
    oh, _u = _login(api, "cn_n")
    p = _product(api, oh, barcode="9500000000008", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_n_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=8)
    missing = _cancel(api, sh, 999999)
    assert missing.status_code == 404
    db = Session()
    try:
        db.get(StockOpname, doc["id"]).status = "POSTED"
        db.commit()
    finally:
        db.close()
    bad = _cancel(api, sh, doc["id"])
    assert bad.status_code == 409
    assert _audit(Session) == []
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "POSTED"
        assert db.get(StockOpname, doc["id"]).cancelled_at is None
    finally:
        db.close()


def test_cancel_rollback_on_persistence_failure(client, monkeypatch):
    api, Session = client
    seed = _seed_owner(Session, username="cn_o")
    oh, _u = _login(api, "cn_o")
    p = _product(api, oh, barcode="9500000000009", stock=12)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_o_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=4)
    before_stock = _stock(Session, p["id"])
    before_mov = _movements(Session, p["id"])

    def boom(*_a, **_k):
        raise HTTPException(500, "persist fail")

    monkeypatch.setattr(ops_mod, "write_audit", boom)
    res = _cancel(api, sh, doc["id"])
    assert res.status_code == 500, res.text
    assert _stock(Session, p["id"]) == before_stock
    assert _movements(Session, p["id"]) == before_mov
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "OPEN"
        assert op.cancelled_at is None
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.counted_qty == 4
        assert ln.difference is None
    finally:
        db.close()
    assert _audit(Session) == []


def test_cancel_preserves_difference_if_already_set(client):
    api, Session = client
    seed = _seed_owner(Session, username="cn_e")
    oh, _u = _login(api, "cn_e")
    p = _product(api, oh, barcode="9500000000010", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "cn_e_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=6)
    db = Session()
    try:
        db.get(StockOpnameLine, line["id"]).difference = -4
        db.commit()
    finally:
        db.close()
    res = _cancel(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    db = Session()
    try:
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.system_qty == 10
        assert ln.counted_qty == 6
        assert ln.difference == -4
    finally:
        db.close()
    assert _adjust_opname(Session, doc["id"]) == 0
    assert _stock(Session, p["id"]) == 10
