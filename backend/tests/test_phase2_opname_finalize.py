"""Phase 2 Step 6D — stock opname finalize / atomic reconciliation."""

from datetime import datetime, timedelta
from pathlib import Path
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

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


def _add_line(api, headers, opname_id, product_id, counted=None):
    body = {"product_id": product_id}
    if counted is not None:
        body["counted_qty"] = counted
    res = api.post(f"/api/stock-opnames/{opname_id}/lines", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _set_counted(api, headers, opname_id, line_id, counted):
    res = api.patch(
        f"/api/stock-opnames/{opname_id}/lines/{line_id}",
        headers=headers,
        json={"counted_qty": counted},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _finalize(api, headers, opname_id):
    return api.post(f"/api/stock-opnames/{opname_id}/finalize", headers=headers)


def _adjust_movements(Session, *, product_id=None, opname_id=None):
    db = Session()
    try:
        q = db.query(StockMovement).filter(StockMovement.kind == "ADJUST", StockMovement.ref_type == "opname")
        if product_id is not None:
            q = q.filter(StockMovement.product_id == product_id)
        if opname_id is not None:
            q = q.filter(StockMovement.ref_id == opname_id)
        return q.all()
    finally:
        db.close()


def _audit(Session, action="stock.opname.finalize"):
    db = Session()
    try:
        return db.query(AuditLog).filter(AuditLog.action == action).all()
    finally:
        db.close()


def _stock(Session, product_id):
    db = Session()
    try:
        return float(db.get(Product, product_id).stock or 0)
    finally:
        db.close()


def test_finalize_success_negative_difference(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_a")
    oh, _u = _login(api, "fn_a")
    p = _product(api, oh, barcode="9400000000001", stock=10, name="Sut A")
    sh, su = _store_headers(api, oh, seed["store_id"], "fn_a_st")
    doc = _create_opname(api, sh, "Sanash A").json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=7)
    assert line["system_qty"] == 10
    assert line["difference"] is None
    before_adj = len(_adjust_movements(Session, product_id=p["id"]))
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == doc["id"]
    assert body["number"] == doc["number"]
    assert body["status"] == "POSTED"
    assert body["posted_at"]
    assert body["line_count"] == 1
    assert _stock(Session, p["id"]) == 7
    movs = _adjust_movements(Session, product_id=p["id"], opname_id=doc["id"])
    assert len(movs) == before_adj + 1
    mv = movs[-1]
    assert mv.kind == "ADJUST"
    assert mv.ref_type == "opname"
    assert mv.ref_id == doc["id"]
    assert mv.qty == -3
    assert mv.balance_after == 7
    db = Session()
    try:
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.difference == -3
        op = db.get(StockOpname, doc["id"])
        assert op.status == "POSTED"
        assert op.posted_at is not None
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
    assert got.json()["status"] == "POSTED"
    assert got.json()["lines"][0]["difference"] == -3


def test_finalize_zero_difference_no_movement(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_b")
    oh, _u = _login(api, "fn_b")
    p = _product(api, oh, barcode="9400000000002", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_b_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=10)
    before = len(_adjust_movements(Session, product_id=p["id"]))
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "POSTED"
    assert _stock(Session, p["id"]) == 10
    assert len(_adjust_movements(Session, product_id=p["id"])) == before
    db = Session()
    try:
        assert db.get(StockOpnameLine, line["id"]).difference == 0
    finally:
        db.close()


def test_finalize_negative_difference_decreases_stock(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_c")
    oh, _u = _login(api, "fn_c")
    p = _product(api, oh, barcode="9400000000003", stock=20, name="Olma")
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_c_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=12)
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    assert _stock(Session, p["id"]) == 12
    mv = _adjust_movements(Session, product_id=p["id"], opname_id=doc["id"])[0]
    assert mv.qty == -8
    assert mv.kind == "ADJUST"


def test_finalize_positive_difference_increases_stock(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_d")
    oh, _u = _login(api, "fn_d")
    p = _product(api, oh, barcode="9400000000004", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_d_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=14)
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    assert _stock(Session, p["id"]) == 14
    mv = _adjust_movements(Session, product_id=p["id"], opname_id=doc["id"])[0]
    assert mv.qty == 4
    assert mv.kind == "ADJUST"
    db = Session()
    try:
        assert db.get(StockOpnameLine, line["id"]).difference == 4
    finally:
        db.close()


def test_finalize_missing_counted_qty_400_no_side_effects(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_e")
    oh, _u = _login(api, "fn_e")
    p = _product(api, oh, barcode="9400000000005", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_e_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"])
    before_adj = len(_adjust_movements(Session))
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 400, res.text
    assert "sanangan miqdor" in res.text.lower()
    assert _stock(Session, p["id"]) == 10
    assert len(_adjust_movements(Session)) == before_adj
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "OPEN"
        assert op.posted_at is None
        ln = db.query(StockOpnameLine).filter(StockOpnameLine.opname_id == doc["id"]).one()
        assert ln.difference is None
        assert ln.counted_qty is None
    finally:
        db.close()
    assert _audit(Session) == []


def test_finalize_negative_counted_qty_400(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_f")
    oh, _u = _login(api, "fn_f")
    p = _product(api, oh, barcode="9400000000006", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_f_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=8)
    db = Session()
    try:
        ln = db.get(StockOpnameLine, line["id"])
        ln.counted_qty = -1
        db.commit()
    finally:
        db.close()
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 400, res.text
    assert _stock(Session, p["id"]) == 10
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
        assert db.get(StockOpnameLine, line["id"]).difference is None
    finally:
        db.close()
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    assert _audit(Session) == []


def test_finalize_negative_resulting_stock_400_rollback(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_g")
    oh, _u = _login(api, "fn_g")
    p = _product(api, oh, barcode="9400000000007", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_g_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=0)
    db = Session()
    try:
        prod = db.get(Product, p["id"])
        prod.stock = 2
        db.commit()
    finally:
        db.close()
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 400, res.text
    assert "qoldiq" in res.text.lower()
    assert _stock(Session, p["id"]) == 2
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "OPEN"
        ln = db.query(StockOpnameLine).filter(StockOpnameLine.opname_id == doc["id"]).one()
        assert ln.difference is None
        assert ln.system_qty == 10
    finally:
        db.close()
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    assert _audit(Session) == []


def test_finalize_atomic_rollback_later_line_failure(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_h")
    oh, _u = _login(api, "fn_h")
    p1 = _product(api, oh, barcode="9400000000008", name="Birinchi", stock=10)
    p2 = _product(api, oh, barcode="9400000000009", name="Ikkinchi", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_h_st")
    doc = _create_opname(api, sh).json()
    l1 = _add_line(api, sh, doc["id"], p1["id"], counted=12)
    l2 = _add_line(api, sh, doc["id"], p2["id"], counted=0)
    db = Session()
    try:
        db.get(Product, p2["id"]).stock = 1
        db.commit()
    finally:
        db.close()
    before1 = _stock(Session, p1["id"])
    before2 = _stock(Session, p2["id"])
    assert before1 == 10 and before2 == 1
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 400, res.text
    assert _stock(Session, p1["id"]) == 10
    assert _stock(Session, p2["id"]) == 1
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "OPEN"
        assert op.posted_at is None
        assert db.get(StockOpnameLine, l1["id"]).difference is None
        assert db.get(StockOpnameLine, l2["id"]).difference is None
    finally:
        db.close()
    assert _audit(Session) == []


def test_finalize_live_stock_after_pos_sale(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_i")
    oh, _u = _login(api, "fn_i")
    p = _product(api, oh, barcode="9400000000010", stock=100)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_i_st")
    cash = _staff(api, oh, username="fn_i_csh", role="CASHIER", store_id=seed["store_id"])
    opened = api.post("/api/shifts/open", headers=cash, json={"opening_cash": 0})
    assert opened.status_code == 200, opened.text
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"])
    assert line["system_qty"] == 100
    sale = api.post(
        "/api/pos/sale",
        headers=cash,
        json={
            "items": [{"product_id": p["id"], "qty": 20}],
            "paid_cash": 224000,
            "payment_type": "CASH",
        },
    )
    assert sale.status_code == 200, sale.text
    assert _stock(Session, p["id"]) == 80
    _set_counted(api, sh, doc["id"], line["id"], 90)
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    assert _stock(Session, p["id"]) == 70
    db = Session()
    try:
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.system_qty == 100
        assert ln.counted_qty == 90
        assert ln.difference == -10
    finally:
        db.close()
    mv = _adjust_movements(Session, product_id=p["id"], opname_id=doc["id"])[0]
    assert mv.qty == -10
    assert mv.balance_after == 70
    assert mv.kind == "ADJUST"
    assert mv.ref_type == "opname"
    assert mv.ref_id == doc["id"]


def test_repeated_finalize_posted_409_no_duplicate(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_j")
    oh, _u = _login(api, "fn_j")
    p = _product(api, oh, barcode="9400000000011", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_j_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    first = _finalize(api, sh, doc["id"])
    assert first.status_code == 200, first.text
    mov_n = len(_adjust_movements(Session, opname_id=doc["id"]))
    stock = _stock(Session, p["id"])
    audits = len(_audit(Session))
    second = _finalize(api, sh, doc["id"])
    assert second.status_code == 409, second.text
    assert _stock(Session, p["id"]) == stock
    assert len(_adjust_movements(Session, opname_id=doc["id"])) == mov_n
    assert len(_audit(Session)) == audits


def test_finalize_cancelled_409(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_k")
    oh, _u = _login(api, "fn_k")
    p = _product(api, oh, barcode="9400000000012", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_k_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        op.status = "CANCELLED"
        op.cancelled_at = datetime.now()
        db.commit()
    finally:
        db.close()
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 409, res.text
    assert _stock(Session, p["id"]) == 10
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "CANCELLED"
    finally:
        db.close()
    assert _audit(Session) == []


def test_finalize_foreign_company_404(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_l")
    oh, _u = _login(api, "fn_l")
    p = _product(api, oh, barcode="9400000000013", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_l_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    seed_b = _seed_owner(Session, username="fn_l_co", company_name="B Co")
    oh2, _u2 = _login(api, "fn_l_co")
    bh, _bu = _store_headers(api, oh2, seed_b["store_id"], "fn_l_b")
    res = _finalize(api, bh, doc["id"])
    assert res.status_code == 404, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    assert _audit(Session) == []


def test_finalize_foreign_store_404(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_m")
    oh, _u = _login(api, "fn_m")
    p = _product(api, oh, barcode="9400000000014", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_m_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Fn", "username": "fn_m_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    bh, _bu = _login(api, "fn_m_b")
    res = _finalize(api, bh, doc["id"])
    assert res.status_code == 404, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10


def test_finalize_cashier_403(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_n")
    oh, _u = _login(api, "fn_n")
    p = _product(api, oh, barcode="9400000000015", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_n_st")
    cash = _staff(api, oh, username="fn_n_csh", role="CASHIER", store_id=seed["store_id"])
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    res = _finalize(api, cash, doc["id"])
    assert res.status_code == 403, res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _adjust_movements(Session, opname_id=doc["id"]) == []


def test_finalize_hq_owner_admin_403(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_o")
    oh, _u = _login(api, "fn_o")
    p = _product(api, oh, barcode="9400000000016", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_o_st")
    doc = _create_opname(api, sh).json()
    _add_line(api, sh, doc["id"], p["id"], counted=9)
    hq = _finalize(api, oh, doc["id"])
    assert hq.status_code == 403, hq.text
    adm = _staff(api, oh, username="fn_o_adm", role="ADMIN", store_id=seed["store_id"])
    admin_res = _finalize(api, adm, doc["id"])
    assert admin_res.status_code == 403, admin_res.text
    db = Session()
    try:
        assert db.get(StockOpname, doc["id"]).status == "OPEN"
    finally:
        db.close()
    assert _stock(Session, p["id"]) == 10
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    assert _audit(Session) == []


def test_audit_only_on_successful_finalize(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_p")
    oh, _u = _login(api, "fn_p")
    p = _product(api, oh, barcode="9400000000017", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_p_st")
    fail_doc = _create_opname(api, sh).json()
    _add_line(api, sh, fail_doc["id"], p["id"])
    bad = _finalize(api, sh, fail_doc["id"])
    assert bad.status_code == 400
    assert _audit(Session) == []
    db = Session()
    try:
        db.get(StockOpname, fail_doc["id"]).status = "CANCELLED"
        db.commit()
    finally:
        db.close()
    ok_doc = _create_opname(api, sh, "ok").json()
    p2 = _product(api, oh, barcode="9400000000018", stock=5, name="Qatiq")
    _add_line(api, sh, ok_doc["id"], p2["id"], counted=5)
    ok = _finalize(api, sh, ok_doc["id"])
    assert ok.status_code == 200, ok.text
    logs = _audit(Session)
    assert len(logs) == 1
    payload = json.loads(logs[0].payload or "{}")
    assert payload["opname_id"] == ok_doc["id"]
    assert payload["line_count"] == 1


def test_finalize_empty_lines_rejected(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_empty")
    oh, _u = _login(api, "fn_empty")
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_empty_st")
    doc = _create_opname(api, sh).json()
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 400, res.text
    assert "qator" in res.text.lower()
    db = Session()
    try:
        op = db.get(StockOpname, doc["id"])
        assert op.status == "OPEN"
        assert op.posted_at is None
        assert db.query(StockOpnameLine).filter(StockOpnameLine.opname_id == doc["id"]).count() == 0
    finally:
        db.close()
    assert _adjust_movements(Session, opname_id=doc["id"]) == []
    assert _audit(Session) == []


def test_finalize_uses_latest_patched_counted_qty(client):
    api, Session = client
    seed = _seed_owner(Session, username="fn_flush")
    oh, _u = _login(api, "fn_flush")
    p = _product(api, oh, barcode="9400000000019", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "fn_flush_st")
    doc = _create_opname(api, sh).json()
    line = _add_line(api, sh, doc["id"], p["id"], counted=5)
    _set_counted(api, sh, doc["id"], line["id"], 8)
    res = _finalize(api, sh, doc["id"])
    assert res.status_code == 200, res.text
    assert _stock(Session, p["id"]) == 8
    db = Session()
    try:
        ln = db.get(StockOpnameLine, line["id"])
        assert ln.counted_qty == 8
        assert ln.difference == -2
    finally:
        db.close()
    movs = _adjust_movements(Session, product_id=p["id"], opname_id=doc["id"])
    assert len(movs) == 1
    assert movs[0].qty == -2


def test_app_js_flushes_counted_before_opname_finalize():
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "app", "web", "assets", "app.js")
    with open(js_path, encoding="utf-8") as fh:
        js = fh.read()
    fn = js.find("async function flushOpnameCountedInputs")
    click = js.find('getElementById("op-finalize")')
    flush_call = js.find("await flushOpnameCountedInputs()", click)
    api_call = js.find("/finalize", click)
    assert fn != -1
    assert click != -1
    assert flush_call != -1
    assert api_call != -1
    assert fn < click
    assert flush_call < api_call


def test_finalize_concurrent_only_one_posted(tmp_path):
    """Two overlapping ASGI finalize calls: CAS allows one POSTED, one 409."""
    import httpx

    _rate.clear()
    db_path = tmp_path / "opname_race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
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
        seed = _seed_owner(Session, username="fn_race")
        oh, _u = _login(api, "fn_race")
        p = _product(api, oh, barcode="9400000000020", stock=10)
        sh, _su = _store_headers(api, oh, seed["store_id"], "fn_race_st")
        doc = _create_opname(api, sh).json()
        _add_line(api, sh, doc["id"], p["id"], counted=7)
        oid = doc["id"]
        url = f"/api/stock-opnames/{oid}/finalize"
        headers = {k: v for k, v in sh.items()}

        async def _race():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                return await asyncio.gather(
                    ac.post(url, headers=headers),
                    ac.post(url, headers=headers),
                )

        r1, r2 = asyncio.run(_race())
        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], (r1.status_code, r1.text, r2.status_code, r2.text)
        assert _stock(Session, p["id"]) == 7
        assert len(_adjust_movements(Session, opname_id=oid)) == 1
        assert len(_audit(Session)) == 1
        db = Session()
        try:
            op = db.get(StockOpname, oid)
            assert op.status == "POSTED"
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()
        _rate.clear()
