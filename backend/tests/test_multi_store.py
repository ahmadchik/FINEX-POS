"""Isolated multi-store tests. In-memory SQLite only — never opens the live POS database."""

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


def _seed_owner(Session, *, username, password="secret12", plan="VIP", status="ACTIVE", store_name="A-Dokon"):
    db = Session()
    try:
        company = Company(
            name="Ahmad Savdo",
            plan=plan,
            status=status,
            currency="UZS",
            locale="uz",
            paid_until=(datetime.now() + timedelta(days=30)) if status == "ACTIVE" else None,
            trial_ends_at=datetime.now() + timedelta(days=30),
        )
        db.add(company)
        db.flush()
        store = Store(company_id=company.id, name=store_name, is_active=True)
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
        return {
            "company_id": company.id,
            "store_id": store.id,
            "user_id": user.id,
            "username": username,
            "password": password,
        }
    finally:
        db.close()


def _login(api, username, password="secret12"):
    res = api.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    data = res.json()
    return data["access"], data["user"], {"Authorization": f"Bearer {data['access']}"}


def test_import_app():
    from app.main import app as loaded

    assert loaded.title


def test_stores_crud_switch_and_isolation(client):
    api, Session = client
    seed = _seed_owner(Session, username="ahmad")
    token, user, headers = _login(api, "ahmad")
    store_a = user["store_id"]
    assert store_a == seed["store_id"]

    listed = api.get("/api/stores", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["current"] is True

    created = api.post(
        "/api/stores",
        headers=headers,
        json={"name": "B-Dokkon", "phone": "99890", "address": "B manzil"},
    )
    assert created.status_code == 200, created.text
    store_b = created.json()["id"]
    assert store_b != store_a

    patched = api.patch(
        f"/api/stores/{store_b}",
        headers=headers,
        json={"name": "B-Dokkon", "phone": "111", "address": "B"},
    )
    assert patched.status_code == 200
    assert patched.json()["phone"] == "111"

    prod_a = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Product A",
            "barcode": "1111111111111",
            "buy_price": 1000,
            "sell_price": 2000,
            "stock": 10,
        },
    )
    assert prod_a.status_code == 200, prod_a.text
    pid_a = prod_a.json()["id"]

    sale_a = api.post(
        "/api/pos/sale",
        headers=headers,
        json={
            "items": [{"product_id": pid_a, "qty": 1}],
            "paid_cash": 2000,
            "payment_type": "CASH",
        },
    )
    assert sale_a.status_code == 200, sale_a.text
    sale_id = sale_a.json()["id"]

    switched = api.post("/api/auth/switch-store", headers=headers, json={"store_id": store_b})
    assert switched.status_code == 200, switched.text
    headers = {"Authorization": f"Bearer {switched.json()['access']}"}
    assert switched.json()["user"]["store_id"] == store_b

    assert api.get("/api/products", headers=headers).json() == []
    assert api.get("/api/sales", headers=headers).json()["items"] == []
    assert api.get(f"/api/sales/{sale_id}", headers=headers).status_code == 404
    assert api.patch(
        f"/api/products/{pid_a}",
        headers=headers,
        json={
            "name": "hack",
            "barcode": "1111111111111",
            "buy_price": 1,
            "sell_price": 2,
            "stock": 0,
        },
    ).status_code == 404
    assert api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": pid_a, "qty": 1}], "paid_cash": 2000, "payment_type": "CASH"},
    ).status_code == 404

    prod_b = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Product B",
            "barcode": "2222222222222",
            "buy_price": 500,
            "sell_price": 800,
            "stock": 5,
        },
    )
    assert prod_b.status_code == 200
    pid_b = prod_b.json()["id"]

    back = api.post("/api/auth/switch-store", headers=headers, json={"store_id": store_a})
    assert back.status_code == 200
    headers = {"Authorization": f"Bearer {back.json()['access']}"}
    names = [p["name"] for p in api.get("/api/products", headers=headers).json()]
    ids = [p["id"] for p in api.get("/api/products", headers=headers).json()]
    assert "Product A" in names
    assert "Product B" not in names
    assert pid_b not in ids
    assert api.get(f"/api/sales/{sale_id}", headers=headers).status_code == 200

    me = api.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["store_id"] == store_a


def test_cashier_cannot_switch_other_store(client):
    api, Session = client
    seed = _seed_owner(Session, username="ownerx")
    _token, user, headers = _login(api, "ownerx")
    store_a = user["store_id"]
    store_b = api.post("/api/stores", headers=headers, json={"name": "C-Dokkon"}).json()["id"]

    staff = api.post(
        "/api/staff",
        headers=headers,
        json={
            "full_name": "Kassir",
            "username": "kassir1",
            "password": "cash12",
            "role": "CASHIER",
            "store_id": store_a,
        },
    )
    assert staff.status_code == 200, staff.text
    login = api.post("/api/auth/login", json={"username": "kassir1", "password": "cash12"})
    assert login.status_code == 200
    ch = {"Authorization": f"Bearer {login.json()['access']}"}
    assert api.get("/api/stores", headers=ch).status_code == 403
    assert api.post("/api/auth/switch-store", headers=ch, json={"store_id": store_b}).status_code == 403
    assert seed["store_id"] == store_a


def test_plan_limit_free_one_store(client):
    api, Session = client
    _seed_owner(Session, username="freeuser", plan="FREE", status="TRIAL")
    _token, _user, headers = _login(api, "freeuser")
    res = api.post("/api/stores", headers=headers, json={"name": "Second"})
    assert res.status_code == 402


def test_company_isolation(client):
    api, Session = client
    _seed_owner(Session, username="owner_a", plan="VIP")
    _seed_owner(Session, username="owner_b", plan="FREE", status="TRIAL", store_name="SB")
    _ta, _ua, ha = _login(api, "owner_a")
    _tb, _ub, hb = _login(api, "owner_b")
    store_a2 = api.post("/api/stores", headers=ha, json={"name": "A2"}).json()["id"]
    ids = [s["id"] for s in api.get("/api/stores", headers=hb).json()]
    assert store_a2 not in ids
    assert api.post("/api/auth/switch-store", headers=hb, json={"store_id": store_a2}).status_code == 404
    assert api.patch(
        f"/api/stores/{store_a2}",
        headers=hb,
        json={"name": "stolen", "phone": "", "address": ""},
    ).status_code == 404


def test_transfer_moves_stock_between_stores(client):
    api, Session = client
    _seed_owner(Session, username="xfer")
    _token, user, headers = _login(api, "xfer")
    store_a = user["store_id"]
    store_b = api.post(
        "/api/stores",
        headers=headers,
        json={"name": "B-X", "username": "store_bx", "password": "secret12"},
    ).json()["id"]
    patched = api.patch(
        f"/api/stores/{store_a}",
        headers=headers,
        json={"name": "A-Dokon", "username": "store_ax", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    prod = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Non",
            "barcode": "3333333333333",
            "buy_price": 1000,
            "sell_price": 1500,
            "stock": 10,
        },
    )
    assert prod.status_code == 200
    pid = prod.json()["id"]
    assert prod.json()["stock"] == 10

    _tok, _su, sh = _login(api, "store_ax")
    xfer = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": store_a,
            "to_store_id": store_b,
            "items": [{"product_id": pid, "qty": 10}],
        },
    )
    assert xfer.status_code == 200, xfer.text

    left = api.get("/api/products", headers=sh).json()
    a_row = next(p for p in left if p["id"] == pid)
    assert a_row["stock"] == 0

    _tokb, _sub, headers = _login(api, "store_bx")
    b_rows = api.get("/api/products", headers=headers).json()
    assert len(b_rows) == 1
    assert b_rows[0]["barcode"] == "3333333333333"
    assert b_rows[0]["stock"] == 10
    hist = api.get("/api/transfers", headers=headers)
    assert hist.status_code == 200
    assert len(hist.json()) >= 1


def test_login_unchanged(client):
    api, Session = client
    _seed_owner(Session, username="logintest")
    bad = api.post("/api/auth/login", json={"username": "logintest", "password": "wrongpw"})
    assert bad.status_code == 401
    ok = api.post("/api/auth/login", json={"username": "logintest", "password": "secret12"})
    assert ok.status_code == 200
    assert ok.json()["access"]
    assert "store_id" in ok.json()["user"]
    assert "stores" in ok.json()["user"]
    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access']}"})
    assert me.status_code == 200

def test_store_login_isolation_and_no_switch(client):
    api, Session = client
    _seed_owner(Session, username="vipowner")
    _token, user, headers = _login(api, "vipowner")
    store_a = user["store_id"]

    prod = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Product A",
            "barcode": "5555555555555",
            "buy_price": 1000,
            "sell_price": 2000,
            "stock": 3,
        },
    )
    assert prod.status_code == 200, prod.text

    created = api.post(
        "/api/stores",
        headers=headers,
        json={"name": "B-Dokkon", "username": "storeb1", "password": "store12", "phone": "", "address": ""},
    )
    assert created.status_code == 200, created.text
    store_b = created.json()["id"]
    assert created.json().get("username") == "storeb1"

    _tok, su, sh = _login(api, "storeb1", "store12")
    assert su["cabinet"] == "store"
    assert su["role"] == "STORE"
    assert su["store_id"] == store_b
    assert api.get("/api/products", headers=sh).json() == []
    assert api.post("/api/auth/switch-store", headers=sh, json={"store_id": store_a}).status_code == 403
    assert api.get("/api/stores", headers=sh).status_code == 403


def test_owner_cannot_write_stock_cash(client):
    api, Session = client
    _seed_owner(Session, username="ownerkirim")
    _token, user, headers = _login(api, "ownerkirim")
    store_a = user["store_id"]
    prod = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Sut",
            "barcode": "4444444444444",
            "buy_price": 1000,
            "sell_price": 2000,
            "stock": 5,
        },
    )
    assert prod.status_code == 200, prod.text
    pid = prod.json()["id"]

    assert api.post(
        "/api/stock-ins",
        headers=headers,
        json={"supplier": "Taminot", "note": "", "items": [{"product_id": pid, "qty": 2, "buy_price": 1000}]},
    ).status_code == 403
    assert api.post("/api/cash", headers=headers, json={"kind": "IN", "amount": 1000, "note": "kirim"}).status_code == 403
    assert api.post("/api/expenses", headers=headers, json={"category": "Boshqa", "amount": 100, "note": "x"}).status_code == 403

    patched = api.patch(
        f"/api/stores/{store_a}",
        headers=headers,
        json={"name": "A-Dokon", "username": "storekirim", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    _tok, su, sh = _login(api, "storekirim")
    assert su["role"] == "STORE"
    sin = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "Taminot", "note": "", "items": [{"product_id": pid, "qty": 2, "buy_price": 1000}]},
    )
    assert sin.status_code == 200, sin.text


def test_empty_barcode_autogen(client):
    api, Session = client
    _seed_owner(Session, username="barcowner")
    _token, user, headers = _login(api, "barcowner")
    store_a = user["store_id"]
    patched = api.patch(
        f"/api/stores/{store_a}",
        headers=headers,
        json={"name": "A-Dokon", "username": "storebarc", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    _tok, _su, sh = _login(api, "storebarc")
    r = api.post(
        "/api/products",
        headers=sh,
        json={"name": "Avto Tovar", "barcode": "", "buy_price": 100, "sell_price": 200, "stock": 1},
    )
    assert r.status_code == 200, r.text
    code = r.json()["barcode"]
    assert len(code) == 13
    dup = api.post(
        "/api/products",
        headers=sh,
        json={"name": "Avto Tovar 2", "barcode": code, "buy_price": 100, "sell_price": 200, "stock": 1},
    )
    assert dup.status_code == 409


def test_owner_change_password_then_login(client):
    api, Session = client
    _seed_owner(Session, username="pwowner", password="secret12")
    _token, _user, headers = _login(api, "pwowner", "secret12")
    res = api.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "secret12", "new_password": "newpass99"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    bad = api.post("/api/auth/login", json={"username": "pwowner", "password": "secret12"})
    assert bad.status_code == 401
    _t2, user2, _h2 = _login(api, "pwowner", "newpass99")
    assert user2["username"] == "pwowner"

