"""Phase 1 Core POS stabilization tests. Isolated in-memory SQLite."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Company, Product, Sale, StockMovement, Store, User
from app.money import CASHIER_MAX_DISCOUNT_PCT, money2, vat_included
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


def _seed_owner(Session, *, username, password="secret12"):
    db = Session()
    try:
        company = Company(
            name="Ahmad Savdo",
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


def test_vat_included_formula():
    assert vat_included(11200, 12) == 1200
    assert vat_included(0, 12) == 0
    assert vat_included(10000, 0) == 0
    assert money2(1.225) == 1.23


def test_sale_tax_inclusive_matches_receipt_and_report(client):
    api, Session = client
    _seed_owner(Session, username="pos_tax")
    _tok, _u, headers = _login(api, "pos_tax")
    p = _product(api, headers)
    sale = api.post(
        "/api/pos/sale",
        headers=headers,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "paid_cash": 11200,
            "payment_type": "CASH",
        },
    )
    assert sale.status_code == 200, sale.text
    data = sale.json()
    assert data["total"] == 11200
    assert data["tax_total"] == 1200
    assert data["tax_inclusive"] is True
    assert data["items"][0]["tax"] == 1200
    got = api.get(f"/api/sales/{data['id']}", headers=headers)
    assert got.json()["tax_total"] == 1200
    dash = api.get("/api/reports/dashboard", headers=headers)
    assert dash.status_code == 200
    assert dash.json()["today"]["tax"] == 1200
    assert dash.json()["today"]["sales"] == 11200


def test_idempotent_sale_not_duplicated(client):
    api, Session = client
    _seed_owner(Session, username="pos_idem")
    _tok, _u, headers = _login(api, "pos_idem")
    p = _product(api, headers, barcode="4780001111113")
    body = {
        "items": [{"product_id": p["id"], "qty": 1}],
        "paid_cash": 11200,
        "payment_type": "CASH",
        "idempotency_key": "same-key-1",
    }
    a = api.post("/api/pos/sale", headers=headers, json=body)
    b = api.post("/api/pos/sale", headers=headers, json=body)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    db = Session()
    try:
        assert db.query(Sale).count() == 1
        assert db.get(Product, p["id"]).stock == 9
    finally:
        db.close()


def test_mixed_payment_and_under_over(client):
    api, Session = client
    _seed_owner(Session, username="pos_mix")
    _tok, _u, headers = _login(api, "pos_mix")
    p = _product(api, headers, barcode="4780001111114", stock=20)
    ok = api.post(
        "/api/pos/sale",
        headers=headers,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "paid_cash": 4000,
            "paid_card": 7200,
            "payment_type": "MIXED",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["payment_type"] == "MIXED"
    assert ok.json()["paid_cash"] == 4000
    assert ok.json()["paid_card"] == 7200
    under = api.post(
        "/api/pos/sale",
        headers=headers,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "paid_cash": 1000,
            "payment_type": "CASH",
        },
    )
    assert under.status_code == 400
    over_card = api.post(
        "/api/pos/sale",
        headers=headers,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "paid_card": 20000,
            "payment_type": "CARD",
        },
    )
    assert over_card.status_code == 400


def test_qty_stock_inactive_and_cashier_discount(client):
    api, Session = client
    seed = _seed_owner(Session, username="pos_disc")
    _tok, user, headers = _login(api, "pos_disc")
    p = _product(api, headers, barcode="4780001111115", stock=2)
    assert api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": p["id"], "qty": 0}], "paid_cash": 11200},
    ).status_code == 400
    assert api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": p["id"], "qty": 3}], "paid_cash": 33600},
    ).status_code == 400
    api.post(f"/api/products/{p['id']}/toggle", headers=headers)
    assert api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": p["id"], "qty": 1}], "paid_cash": 11200},
    ).status_code == 400
    api.post(f"/api/products/{p['id']}/toggle", headers=headers)

    staff = api.post(
        "/api/staff",
        headers=headers,
        json={
            "full_name": "Kassir",
            "username": "poskassir",
            "password": "cash12",
            "role": "CASHIER",
            "store_id": seed["store_id"],
        },
    )
    assert staff.status_code == 200, staff.text
    login = api.post("/api/auth/login", json={"username": "poskassir", "password": "cash12"})
    ch = {"Authorization": f"Bearer {login.json()['access']}"}
    opened = api.post("/api/shifts/open", headers=ch, json={"opening_cash": 0})
    assert opened.status_code == 200, opened.text
    too_big = api.post(
        "/api/pos/sale",
        headers=ch,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "discount": 5600,
            "paid_cash": 5600,
            "payment_type": "CASH",
        },
    )
    assert too_big.status_code == 403
    cap = money2(11200 * CASHIER_MAX_DISCOUNT_PCT / 100)
    ok = api.post(
        "/api/pos/sale",
        headers=ch,
        json={
            "items": [{"product_id": p["id"], "qty": 1}],
            "discount": cap,
            "paid_cash": 11200 - cap,
            "payment_type": "CASH",
        },
    )
    assert ok.status_code == 200, ok.text
    db = Session()
    try:
        actions = [a.action for a in db.query(AuditLog).all()]
        assert "sale.create" in actions
        assert "sale.discount" in actions
    finally:
        db.close()


def test_return_cannot_exceed_sold_and_restores_stock(client):
    api, Session = client
    _seed_owner(Session, username="pos_ret")
    _tok, _u, headers = _login(api, "pos_ret")
    p = _product(api, headers, barcode="4780001111116", stock=5)
    sale = api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": p["id"], "qty": 2}], "paid_cash": 22400},
    ).json()
    item_id = sale["items"][0]["id"]
    bad = api.post(
        f"/api/sales/{sale['id']}/return",
        headers=headers,
        json={"items": [{"id": item_id, "qty": 3}]},
    )
    assert bad.status_code == 400
    part = api.post(
        f"/api/sales/{sale['id']}/return",
        headers=headers,
        json={"items": [{"id": item_id, "qty": 1}]},
    )
    assert part.status_code == 200
    assert part.json()["status"] == "PARTIAL"
    again = api.post(
        f"/api/sales/{sale['id']}/return",
        headers=headers,
        json={"items": [{"id": item_id, "qty": 2}]},
    )
    assert again.status_code == 400
    db = Session()
    try:
        assert db.get(Product, p["id"]).stock == 4
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()]
        assert "SALE" in kinds and "RETURN" in kinds
    finally:
        db.close()
    staff = api.post(
        "/api/staff",
        headers=headers,
        json={"full_name": "K", "username": "retcash", "password": "cash12", "role": "CASHIER", "store_id": _u["store_id"]},
    )
    login = api.post("/api/auth/login", json={"username": "retcash", "password": "cash12"})
    ch = {"Authorization": f"Bearer {login.json()['access']}"}
    assert api.post(f"/api/sales/{sale['id']}/return", headers=ch, json={"items": []}).status_code == 403
