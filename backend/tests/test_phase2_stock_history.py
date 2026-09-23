"""Phase 2 Step 3 — read-only stock movement API."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Company, Store, User
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
            full_name="Ali",
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
        "sku": "ST-001",
        **kw,
    }
    res = api.post("/api/products", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _store_headers(api, owner_headers, store_id, username):
    patched = api.patch(
        f"/api/stores/{store_id}",
        headers=owner_headers,
        json={"name": "A-Dokon", "username": username, "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    h, user = _login(api, username)
    return h, user


def test_stock_movements_unauthenticated(client):
    api, _Session = client
    assert api.get("/api/stock-movements").status_code == 401


def test_stock_movements_cashier_forbidden(client):
    api, Session = client
    seed = _seed_owner(Session, username="hist_own")
    oh, _u = _login(api, "hist_own")
    staff = api.post(
        "/api/staff",
        headers=oh,
        json={
            "full_name": "Kassir",
            "username": "hist_cash",
            "password": "cash12",
            "role": "CASHIER",
            "store_id": seed["store_id"],
        },
    )
    assert staff.status_code == 200, staff.text
    login = api.post("/api/auth/login", json={"username": "hist_cash", "password": "cash12"})
    ch = {"Authorization": f"Bearer {login.json()['access']}"}
    assert api.get("/api/stock-movements", headers=ch).status_code == 403


def test_stock_movements_tenant_and_store_isolation(client):
    api, Session = client
    seed_a = _seed_owner(Session, username="hist_a")
    oh, _ua = _login(api, "hist_a")
    pa = _product(api, oh, barcode="7000000000001")
    _seed_owner(Session, username="hist_b", company_name="B Co")
    bh, _ub = _login(api, "hist_b")
    listed_b = api.get("/api/stock-movements", headers=bh)
    assert listed_b.status_code == 200
    assert all(row["product_id"] != pa["id"] for row in listed_b.json())
    steal = api.get("/api/stock-movements", headers=bh, params={"product_id": pa["id"]})
    assert steal.status_code == 404

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Dok", "username": "hist_store_b", "password": "secret12"},
    )
    assert store_b.status_code == 200
    sh, _su = _login(api, "hist_store_b")
    other_store = api.get("/api/stock-movements", headers=sh, params={"product_id": pa["id"]})
    assert other_store.status_code == 404


def test_stock_movements_filters_pagination_and_kinds(client):
    api, Session = client
    seed = _seed_owner(Session, username="hist_f")
    oh, user = _login(api, "hist_f")
    p = _product(api, oh, barcode="7100000000001", stock=10, sku="ST-001")
    today = datetime.now().strftime("%Y-%m-%d")

    sh, _su = _store_headers(api, oh, seed["store_id"], "hist_store_a")
    kirim = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "Vali", "items": [{"product_id": p["id"], "qty": 20, "buy_price": 8000}]},
    )
    assert kirim.status_code == 200, kirim.text

    sale = api.post(
        "/api/pos/sale",
        headers=oh,
        json={"items": [{"product_id": p["id"], "qty": 3}], "paid_cash": 33600, "payment_type": "CASH"},
    )
    assert sale.status_code == 200, sale.text
    item_id = sale.json()["items"][0]["id"]
    ret = api.post(
        f"/api/sales/{sale.json()['id']}/return",
        headers=oh,
        json={"items": [{"id": item_id, "qty": 1}]},
    )
    assert ret.status_code == 200, ret.text

    adj = api.post(
        "/api/stock-adjustments",
        headers=oh,
        json={"product_id": p["id"], "qty": 12, "reason": "Physical count difference"},
    )
    assert adj.status_code == 200, adj.text
    assert adj.json()["kind"] == "ADJUST"

    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "C-Dok", "username": "hist_store_c", "password": "secret12"},
    )
    assert store_b.status_code == 200
    xfer = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed["store_id"],
            "to_store_id": store_b.json()["id"],
            "items": [{"product_id": p["id"], "qty": 2}],
        },
    )
    assert xfer.status_code == 200, xfer.text

    all_rows = api.get("/api/stock-movements", headers=oh, params={"product_id": p["id"], "limit": 50})
    assert all_rows.status_code == 200
    kinds = {r["kind"] for r in all_rows.json()}
    assert {"OPENING", "IN", "SALE", "RETURN", "ADJUST", "TRANSFER_OUT"} <= kinds
    sale_row = next(r for r in all_rows.json() if r["kind"] == "SALE")
    assert sale_row["qty"] == -3
    assert sale_row["product_id"] == p["id"]
    assert sale_row["sku"] == "ST-001"
    assert sale_row["barcode"] == "7100000000001"
    assert sale_row["user_name"]
    assert sale_row["balance_after"] is not None
    in_row = next(r for r in all_rows.json() if r["kind"] == "IN")
    assert in_row["qty"] == 20
    xfer_row = next(r for r in all_rows.json() if r["kind"] == "TRANSFER_OUT")
    assert xfer_row["ref_type"] == "transfer"
    assert xfer_row["ref_id"] == xfer.json()["id"]

    only_sale = api.get("/api/stock-movements", headers=oh, params={"product_id": p["id"], "kind": "SALE"})
    assert only_sale.status_code == 200
    assert only_sale.json() and all(r["kind"] == "SALE" for r in only_sale.json())

    by_day = api.get("/api/stock-movements", headers=oh, params={"product_id": p["id"], "from": today, "to": today})
    assert by_day.status_code == 200
    assert len(by_day.json()) >= 1
    future = api.get(
        "/api/stock-movements",
        headers=oh,
        params={"product_id": p["id"], "from": "2099-01-01", "to": "2099-01-02"},
    )
    assert future.status_code == 200
    assert future.json() == []

    page1 = api.get("/api/stock-movements", headers=oh, params={"product_id": p["id"], "page": 1, "limit": 2})
    assert page1.status_code == 200
    assert len(page1.json()) == 2
    assert int(page1.headers.get("X-Total-Count") or 0) >= 6
    assert page1.headers.get("X-Limit") == "2"
    page2 = api.get("/api/stock-movements", headers=oh, params={"product_id": p["id"], "page": 2, "limit": 2})
    assert page2.json()[0]["id"] != page1.json()[0]["id"]
    capped = api.get("/api/stock-movements", headers=oh, params={"limit": 9999})
    assert capped.headers.get("X-Limit") == "200"
    default = api.get("/api/stock-movements", headers=oh)
    assert default.headers.get("X-Limit") == "50"
