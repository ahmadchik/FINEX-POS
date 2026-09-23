"""Phase 2 Step 4 — dedicated difference-based stock adjustment."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Product, StockMovement, Company, Store, User
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


def _adjust(api, headers, product_id, qty, reason="Physical count difference"):
    return api.post(
        "/api/stock-adjustments",
        headers=headers,
        json={"product_id": product_id, "qty": qty, "reason": reason},
    )


def test_adjust_plus_five_and_minus_three(client):
    api, Session = client
    _seed_owner(Session, username="adj_norm")
    h, _u = _login(api, "adj_norm")
    p = _product(api, h, barcode="8100000000001", stock=100)
    up = _adjust(api, h, p["id"], 5, "Count plus")
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["stock_before"] == 100
    assert body["qty"] == 5
    assert body["stock_after"] == 105
    assert body["kind"] == "ADJUST"
    assert body["reason"] == "Count plus"
    assert body["movement_id"]
    down = _adjust(api, h, p["id"], -3, "Physical count difference")
    assert down.status_code == 200, down.text
    assert down.json()["stock_before"] == 105
    assert down.json()["qty"] == -3
    assert down.json()["stock_after"] == 102
    db = Session()
    try:
        prod = db.get(Product, p["id"])
        assert prod.stock == 102
        rows = (
            db.query(StockMovement)
            .filter(StockMovement.product_id == p["id"], StockMovement.kind == "ADJUST")
            .order_by(StockMovement.id)
            .all()
        )
        assert [r.qty for r in rows] == [5, -3]
        assert rows[-1].balance_after == 102
        assert rows[-1].note == "Physical count difference"
        assert rows[-1].user_id
        assert rows[-1].ref_type == "stock_adjust"
    finally:
        db.close()


def test_adjust_validation_zero_invalid_inactive_qty_negative(client):
    api, Session = client
    _seed_owner(Session, username="adj_val")
    h, _u = _login(api, "adj_val")
    p = _product(api, h, barcode="8100000000002", stock=10)
    zero = _adjust(api, h, p["id"], 0)
    assert zero.status_code == 400
    missing = api.post("/api/stock-adjustments", headers=h, json={"product_id": 999999, "qty": 1, "reason": "ghost product"})
    assert missing.status_code == 404
    toggled = api.post(f"/api/products/{p['id']}/toggle", headers=h)
    assert toggled.status_code == 200
    assert toggled.json()["is_active"] is False
    inactive = _adjust(api, h, p["id"], 1, "Inactive try")
    assert inactive.status_code == 400
    api.post(f"/api/products/{p['id']}/toggle", headers=h)
    bad = api.post(
        "/api/stock-adjustments",
        headers=h,
        json={"product_id": p["id"], "qty": "not-a-number", "reason": "bad qty"},
    )
    assert bad.status_code == 422
    neg = _adjust(api, h, p["id"], -11, "Would go negative")
    assert neg.status_code == 400
    listed = api.get("/api/products", headers=h)
    assert listed.status_code == 200
    assert next(x["stock"] for x in listed.json() if x["id"] == p["id"]) == 10


def test_adjust_permissions_roles_and_isolation(client):
    api, Session = client
    seed = _seed_owner(Session, username="adj_own")
    oh, _u = _login(api, "adj_own")
    p = _product(api, oh, barcode="8100000000003", stock=20)
    owner_ok = _adjust(api, oh, p["id"], 1, "Owner ok")
    assert owner_ok.status_code == 200, owner_ok.text

    admin_h = _staff(api, oh, username="adj_admin", role="ADMIN", store_id=seed["store_id"])
    admin_ok = _adjust(api, admin_h, p["id"], 1, "Admin ok")
    assert admin_ok.status_code == 200, admin_ok.text

    wh_h = _staff(api, oh, username="adj_wh", role="WAREHOUSE", store_id=seed["store_id"])
    wh_ok = _adjust(api, wh_h, p["id"], 1, "Warehouse ok")
    assert wh_ok.status_code == 200, wh_ok.text

    mgr_h = _staff(api, oh, username="adj_mgr", role="MANAGER", store_id=seed["store_id"])
    mgr_ok = _adjust(api, mgr_h, p["id"], 1, "Manager ok")
    assert mgr_ok.status_code == 200, mgr_ok.text

    cash_h = _staff(api, oh, username="adj_cash", role="CASHIER", store_id=seed["store_id"])
    cash = _adjust(api, cash_h, p["id"], 1, "Cashier no")
    assert cash.status_code == 403

    _seed_owner(Session, username="adj_b", company_name="B Co")
    bh, _ub = _login(api, "adj_b")
    cross_co = _adjust(api, bh, p["id"], 1, "Cross company")
    assert cross_co.status_code == 404

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Dok", "username": "adj_store_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    sh, _su = _login(api, "adj_store_b")
    cross_store = _adjust(api, sh, p["id"], 1, "Cross store")
    assert cross_store.status_code == 404


def test_adjust_ledger_audit_history(client):
    api, Session = client
    _seed_owner(Session, username="adj_aud")
    h, user = _login(api, "adj_aud")
    p = _product(api, h, barcode="8100000000004", stock=100, sku="ST-ADJ")
    res = _adjust(api, h, p["id"], -3, "Physical count difference")
    assert res.status_code == 200, res.text
    assert res.json()["stock_after"] == 97
    hist = api.get("/api/stock-movements", headers=h, params={"product_id": p["id"], "kind": "ADJUST"})
    assert hist.status_code == 200
    rows = hist.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "ADJUST"
    assert row["qty"] == -3
    assert row["balance_after"] == 97
    assert row["note"] == "Physical count difference"
    assert row["user_name"]
    assert row["sku"] == "ST-ADJ"
    db = Session()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == "stock.adjust").all()
        assert len(logs) == 1
        assert logs[0].user_id == user["id"]
        assert logs[0].entity == "product"
        assert logs[0].entity_id == p["id"]
        assert '"qty": -3' in (logs[0].payload or "") or "-3" in (logs[0].payload or "")
        assert "Physical count difference" in (logs[0].payload or "")
        mov = db.query(StockMovement).filter(StockMovement.id == res.json()["movement_id"]).one()
        assert mov.kind == "ADJUST"
        assert mov.qty == -3
        assert mov.balance_after == 97
        assert mov.company_id == user["company_id"]
        assert mov.store_id
        assert mov.product_id == p["id"]
        assert mov.user_id == user["id"]
        assert mov.created_at is not None
    finally:
        db.close()


def test_adjust_duplicate_post_is_additive_not_idempotent(client):
    """Sale idempotency_key is sale-only; ADJUST is difference-based and additive."""
    api, Session = client
    _seed_owner(Session, username="adj_idem")
    h, _u = _login(api, "adj_idem")
    p = _product(api, h, barcode="8100000000005", stock=10)
    body = {"product_id": p["id"], "qty": 5, "reason": "Same body twice"}
    a = api.post("/api/stock-adjustments", headers=h, json=body)
    b = api.post("/api/stock-adjustments", headers=h, json=body)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["stock_after"] == 15
    assert b.json()["stock_after"] == 20
    db = Session()
    try:
        n = (
            db.query(StockMovement)
            .filter(StockMovement.product_id == p["id"], StockMovement.kind == "ADJUST")
            .count()
        )
        assert n == 2
        assert db.get(Product, p["id"]).stock == 20
    finally:
        db.close()


def test_patch_cannot_adjust_stock_sale_return_transfer_opening(client):
    api, Session = client
    seed = _seed_owner(Session, username="adj_reg")
    h, _u = _login(api, "adj_reg")
    p = _product(api, h, barcode="8100000000006", stock=7)
    patched = api.patch(
        f"/api/products/{p['id']}",
        headers=h,
        json={"name": "Sut tuzatilgan", "barcode": "8100000000006", "sell_price": 11200, "buy_price": 8000, "stock": 99},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Sut tuzatilgan"
    assert patched.json()["stock"] == 7
    db = Session()
    try:
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()]
        assert kinds == ["OPENING"]
        assert db.get(Product, p["id"]).stock == 7
    finally:
        db.close()
    sale = api.post(
        "/api/pos/sale",
        headers=h,
        json={"items": [{"product_id": p["id"], "qty": 1}], "paid_cash": 11200, "payment_type": "CASH"},
    )
    assert sale.status_code == 200, sale.text
    item_id = sale.json()["items"][0]["id"]
    ret = api.post(
        f"/api/sales/{sale.json()['id']}/return",
        headers=h,
        json={"items": [{"id": item_id, "qty": 1}]},
    )
    assert ret.status_code == 200, ret.text
    store_b = api.post(
        "/api/stores",
        headers=h,
        json={"name": "B-St", "username": "adj_reg_b", "password": "secret12"},
    )
    assert store_b.status_code == 200
    patched_src = api.patch(
        f"/api/stores/{seed['store_id']}",
        headers=h,
        json={"name": "A-Dokon", "username": "adj_reg_a", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched_src.status_code == 200, patched_src.text
    sa, _ua = _login(api, "adj_reg_a")
    xfer = api.post(
        "/api/transfers",
        headers=sa,
        json={
            "from_store_id": seed["store_id"],
            "to_store_id": store_b.json()["id"],
            "items": [{"product_id": p["id"], "qty": 1}],
        },
    )
    assert xfer.status_code == 200, xfer.text
    db = Session()
    try:
        kinds = {m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()}
        assert {"OPENING", "SALE", "RETURN", "TRANSFER_OUT"} <= kinds
        assert "ADJUST" not in kinds
    finally:
        db.close()
