"""Phase 2 Step 2 — product master, SKU/barcode uniqueness, pagination, isolation."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Company, Product, StockMovement, Store, User
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
    return data["access"], data["user"], {"Authorization": f"Bearer {data['access']}"}


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


def test_sku_unique_empty_and_cross_scope(client):
    api, Session = client
    _seed_owner(Session, username="sku_a")
    _tok, _u, ha = _login(api, "sku_a")
    a = _product(api, ha, barcode="1000000000001", sku="ST-001")
    assert a["sku"] == "ST-001"
    dup = api.post(
        "/api/products",
        headers=ha,
        json={"name": "Qatiq", "barcode": "1000000000002", "sku": "ST-001", "sell_price": 1000, "buy_price": 500},
    )
    assert dup.status_code == 409
    empty1 = _product(api, ha, barcode="1000000000003", sku="", name="Bo'sh1")
    empty2 = _product(api, ha, barcode="1000000000004", sku="", name="Bo'sh2")
    assert empty1["sku"] == "" and empty2["sku"] == ""
    other = _product(api, ha, barcode="1000000000006", sku="ST-002", name="Boshqa")
    patch_dup = api.patch(
        f"/api/products/{other['id']}",
        headers=ha,
        json={
            "name": "Boshqa",
            "barcode": "1000000000006",
            "sku": "ST-001",
            "sell_price": 1000,
            "buy_price": 500,
        },
    )
    assert patch_dup.status_code == 409

    store_b = api.post(
        "/api/stores",
        headers=ha,
        json={"name": "B-Dokon", "username": "store_sku_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    _tokb, _ub, hb = _login(api, "store_sku_b")
    other_store = api.post(
        "/api/products",
        headers=hb,
        json={"name": "Sut B", "barcode": "1000000000005", "sku": "ST-001", "sell_price": 1000, "buy_price": 500},
    )
    assert other_store.status_code == 200, other_store.text

    _seed_owner(Session, username="sku_co_b", company_name="B Comp")
    _tokc, _uc, hc = _login(api, "sku_co_b")
    other_co = api.post(
        "/api/products",
        headers=hc,
        json={"name": "Sut C", "barcode": "1000000000001", "sku": "ST-001", "sell_price": 1000, "buy_price": 500},
    )
    assert other_co.status_code == 200, other_co.text


def test_barcode_unique_generate_and_collision(client):
    api, Session = client
    _seed_owner(Session, username="bar_a")
    _tok, _u, ha = _login(api, "bar_a")
    p = _product(api, ha, barcode="2000000000001")
    assert p["barcode"] == "2000000000001"
    dup = api.post(
        "/api/products",
        headers=ha,
        json={"name": "Dup", "barcode": "2000000000001", "sell_price": 1000, "buy_price": 1},
    )
    assert dup.status_code == 409
    other_bar = _product(api, ha, barcode="2000000000002", name="OtherBar")
    patch_bar = api.patch(
        f"/api/products/{other_bar['id']}",
        headers=ha,
        json={"name": "OtherBar", "barcode": "2000000000001", "sell_price": 1000, "buy_price": 1},
    )
    assert patch_bar.status_code == 409
    gen = api.post(
        "/api/products",
        headers=ha,
        json={"name": "Avto", "barcode": "", "sell_price": 1000, "buy_price": 1},
    )
    assert gen.status_code == 200, gen.text
    assert gen.json()["barcode"]
    assert len(gen.json()["barcode"]) == 13

    store_b = api.post(
        "/api/stores",
        headers=ha,
        json={"name": "B-Bar", "username": "store_bar_b", "password": "secret12"},
    )
    assert store_b.status_code == 200
    _tokb, _ub, hb = _login(api, "store_bar_b")
    same_bar_other_store = api.post(
        "/api/products",
        headers=hb,
        json={"name": "Clone", "barcode": "2000000000001", "sell_price": 1000, "buy_price": 1},
    )
    assert same_bar_other_store.status_code == 200

    _seed_owner(Session, username="bar_co_b", company_name="Bar Co B")
    _tokc, _uc, hc = _login(api, "bar_co_b")
    same_bar_other_co = api.post(
        "/api/products",
        headers=hc,
        json={"name": "CoB", "barcode": "2000000000001", "sell_price": 1000, "buy_price": 1},
    )
    assert same_bar_other_co.status_code == 200


def test_search_exact_barcode_then_substring(client):
    api, Session = client
    _seed_owner(Session, username="srch")
    _tok, _u, h = _login(api, "srch")
    exact = _product(api, h, name="Exact", barcode="4780009999991", sku="EX-1")
    _product(api, h, name="Contains 4780009999991 in name", barcode="1111111111116", sku="SUB")
    _product(api, h, name="Other", barcode="2222222222222", sku="OT-1")
    got = api.get("/api/products", headers=h, params={"q": "4780009999991"})
    assert got.status_code == 200
    ids = [p["id"] for p in got.json()]
    assert ids == [exact["id"]]
    pos = api.get("/api/pos/products", headers=h, params={"q": "4780009999991"})
    assert pos.status_code == 200
    assert [p["id"] for p in pos.json()] == [exact["id"]]
    sku = api.get("/api/products", headers=h, params={"q": "OT-1"})
    assert any(p["sku"] == "OT-1" for p in sku.json())
    name = api.get("/api/products", headers=h, params={"q": "Contains"})
    assert any("Contains" in p["name"] for p in name.json())
    sub = api.get("/api/products", headers=h, params={"q": "111111"})
    assert any(p["barcode"] == "1111111111116" for p in sub.json())


def test_product_pagination_and_headers(client):
    api, Session = client
    _seed_owner(Session, username="pageu")
    _tok, _u, h = _login(api, "pageu")
    for i in range(12):
        _product(
            api,
            h,
            name=f"P{i:02d}",
            barcode=f"30000000000{i:02d}"[:13].ljust(13, "0") if False else f"3{i:012d}",
            sku=f"PG-{i}",
            stock=1,
        )
    page1 = api.get("/api/products", headers=h, params={"page": 1, "limit": 5})
    assert page1.status_code == 200
    assert len(page1.json()) == 5
    assert page1.headers.get("X-Total-Count") == "12"
    assert page1.headers.get("X-Limit") == "5"
    page3 = api.get("/api/products", headers=h, params={"page": 3, "limit": 5})
    assert len(page3.json()) == 2
    empty = api.get("/api/products", headers=h, params={"page": 99, "limit": 5})
    assert empty.json() == []
    capped = api.get("/api/products", headers=h, params={"page": 1, "limit": 9999})
    assert capped.headers.get("X-Limit") == "500"
    assert len(capped.json()) == 12
    default = api.get("/api/products", headers=h)
    assert default.headers.get("X-Limit") == "200"


def test_category_isolation_and_fields(client):
    api, Session = client
    _seed_owner(Session, username="cata")
    _tok, ua, ha = _login(api, "cata")
    cat = api.post("/api/categories", headers=ha, json={"name": "Ichimlik"})
    assert cat.status_code == 200
    cid = cat.json()["id"]
    p = _product(api, ha, barcode="4000000000001", category_id=cid, manufacturer="Santen", sku="CAT-1")
    assert p["category_id"] == cid
    assert p["category_name"] == "Ichimlik"
    assert p["manufacturer"] == "Santen"
    _seed_owner(Session, username="catb", company_name="B")
    _tokb, ub, hb = _login(api, "catb")
    steal = api.post(
        "/api/products",
        headers=hb,
        json={"name": "Steal", "barcode": "4000000000002", "category_id": cid, "sell_price": 1, "buy_price": 1},
    )
    assert steal.status_code == 400
    foreign = api.get(f"/api/products/{p['id']}", headers=hb)
    assert foreign.status_code in (404, 405)
    listed = api.get("/api/products", headers=hb)
    assert all(row["id"] != p["id"] for row in listed.json())
    patch = api.patch(
        f"/api/products/{p['id']}",
        headers=hb,
        json={"name": "Hack", "barcode": "4000000000001", "sell_price": 1, "buy_price": 1},
    )
    assert patch.status_code == 404


def test_opening_stock_uses_move_stock_and_patch_adjust(client):
    api, Session = client
    seed = _seed_owner(Session, username="stk")
    _tok, _u, h = _login(api, "stk")
    p = _product(api, h, barcode="5000000000001", stock=7)
    assert p["stock"] == 7
    db = Session()
    try:
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()]
        assert "OPENING" in kinds
    finally:
        db.close()
    patched = api.patch(
        f"/api/products/{p['id']}",
        headers=h,
        json={"name": "Sut", "barcode": "5000000000001", "sell_price": 11200, "buy_price": 8000, "stock": 9},
    )
    assert patched.status_code == 200
    assert patched.json()["stock"] == 7
    adj = api.post(
        "/api/stock-adjustments",
        headers=h,
        json={"product_id": p["id"], "qty": 2, "reason": "Physical count plus"},
    )
    assert adj.status_code == 200, adj.text
    assert adj.json()["stock_before"] == 7
    assert adj.json()["qty"] == 2
    assert adj.json()["stock_after"] == 9
    db = Session()
    try:
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()]
        assert "OPENING" in kinds and "ADJUST" in kinds
        assert db.get(Product, p["id"]).stock == 9
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
    assert ret.status_code == 200
    store_b = api.post(
        "/api/stores",
        headers=h,
        json={"name": "B-St", "username": "store_st_b", "password": "secret12"},
    )
    assert store_b.status_code == 200
    patched_src = api.patch(
        f"/api/stores/{seed['store_id']}",
        headers=h,
        json={"name": "A-Dokon", "username": "store_st_a", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched_src.status_code == 200, patched_src.text
    _ta, _ua, sa = _login(api, "store_st_a")
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


def test_hq_product_write_allowed_kirim_blocked(client):
    api, Session = client
    _seed_owner(Session, username="hqpol")
    _tok, user, h = _login(api, "hqpol")
    assert user["cabinet"] == "company" or user["role"] == "OWNER"
    p = _product(api, h, barcode="6000000000001", stock=2)
    kirim = api.post(
        "/api/stock-ins",
        headers=h,
        json={"supplier": "X", "items": [{"product_id": p["id"], "qty": 1, "buy_price": 1}]},
    )
    assert kirim.status_code == 403


def test_cashier_cannot_manage_products(client):
    api, Session = client
    seed = _seed_owner(Session, username="cashprod")
    _tok, _u, h = _login(api, "cashprod")
    staff = api.post(
        "/api/staff",
        headers=h,
        json={
            "full_name": "K",
            "username": "cashp2",
            "password": "cash12",
            "role": "CASHIER",
            "store_id": seed["store_id"],
        },
    )
    assert staff.status_code == 200, staff.text
    login = api.post("/api/auth/login", json={"username": "cashp2", "password": "cash12"})
    ch = {"Authorization": f"Bearer {login.json()['access']}"}
    assert api.get("/api/products", headers=ch).status_code == 403
