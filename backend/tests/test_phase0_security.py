"""Phase 0 security foundation tests. Isolated in-memory SQLite — never opens live POS DB."""

from datetime import datetime, timedelta
import base64
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import (
    JWT_DEV_PLACEHOLDER,
    PLATFORM_DEV_PASSWORD_PLACEHOLDER,
    Settings,
    validate_runtime_secrets,
)
from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, BillingPayment, Company, Product, StockMovement, Store, User
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


def _click_body(ref, secret, amount="80000"):
    body = {
        "click_trans_id": "1001",
        "service_id": "10",
        "merchant_trans_id": ref,
        "amount": amount,
        "action": "1",
        "sign_time": "2026-09-18",
    }
    raw = (
        f"{body['click_trans_id']}{body['service_id']}{secret}"
        f"{body['merchant_trans_id']}{body['amount']}"
        f"{body['action']}{body['sign_time']}"
    )
    body["sign_string"] = hashlib.md5(raw.encode()).hexdigest()
    return body


def _create_pending_payment(api, headers, Session):
    res = api.post("/api/billing/checkout", headers=headers, json={"plan": "PRO", "method": "click"})
    assert res.status_code == 200, res.text
    pid = res.json()["payment_id"]
    db = Session()
    try:
        pay = db.get(BillingPayment, pid)
        return pid, pay.provider_ref, pay.company_id
    finally:
        db.close()


def test_demo_pay_unauthenticated_rejected(client):
    api, Session = client
    seed = _seed_owner(Session, username="bill_owner")
    _tok, _u, headers = _login(api, "bill_owner")
    pid, _ref, _cid = _create_pending_payment(api, headers, Session)
    res = api.post(f"/api/billing/demo-pay/{pid}/confirm")
    assert res.status_code == 401
    db = Session()
    try:
        assert db.get(BillingPayment, pid).status == "pending"
        assert db.get(Company, seed["company_id"]).plan == "VIP"
    finally:
        db.close()


def test_demo_pay_owner_can_confirm(client):
    api, Session = client
    seed = _seed_owner(Session, username="bill_ok")
    _tok, _u, headers = _login(api, "bill_ok")
    pid, _ref, cid = _create_pending_payment(api, headers, Session)
    res = api.post(f"/api/billing/demo-pay/{pid}/confirm", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    db = Session()
    try:
        pay = db.get(BillingPayment, pid)
        company = db.get(Company, cid)
        assert pay.status == "paid"
        assert company.plan == "PRO"
        assert company.status == "ACTIVE"
        actions = [a.action for a in db.query(AuditLog).filter(AuditLog.company_id == seed["company_id"]).all()]
        assert "billing.activate" in actions
    finally:
        db.close()


def test_demo_pay_wrong_company_rejected(client):
    api, Session = client
    _seed_owner(Session, username="bill_a")
    seed_b = _seed_owner(Session, username="bill_b", store_name="B-Dokon")
    _ta, _ua, ha = _login(api, "bill_a")
    _tb, _ub, hb = _login(api, "bill_b")
    pid, _ref, cid_a = _create_pending_payment(api, ha, Session)
    res = api.post(f"/api/billing/demo-pay/{pid}/confirm", headers=hb)
    assert res.status_code == 404
    db = Session()
    try:
        assert db.get(BillingPayment, pid).status == "pending"
        assert db.get(Company, cid_a).plan == "VIP"
        assert db.get(Company, seed_b["company_id"]).plan == "VIP"
    finally:
        db.close()


def test_click_webhook_missing_secret_rejected(client, monkeypatch):
    api, Session = client
    from app.config import settings

    monkeypatch.setattr(settings, "click_secret", "")
    _seed_owner(Session, username="wh_empty")
    _tok, _u, headers = _login(api, "wh_empty")
    pid, ref, _cid = _create_pending_payment(api, headers, Session)
    body = _click_body(ref, "not-used")
    res = api.post("/api/billing/webhook/click", json=body)
    assert res.status_code == 503
    db = Session()
    try:
        assert db.get(BillingPayment, pid).status == "pending"
    finally:
        db.close()


def test_click_webhook_missing_and_invalid_signature(client, monkeypatch):
    api, Session = client
    from app.config import settings

    secret = "unit-test-click-secret"
    monkeypatch.setattr(settings, "click_secret", secret)
    _seed_owner(Session, username="wh_sign")
    _tok, _u, headers = _login(api, "wh_sign")
    pid, ref, _cid = _create_pending_payment(api, headers, Session)
    missing = _click_body(ref, secret)
    missing.pop("sign_string")
    assert api.post("/api/billing/webhook/click", json=missing).status_code == 403
    bad = _click_body(ref, secret)
    bad["sign_string"] = "0" * 32
    assert api.post("/api/billing/webhook/click", json=bad).status_code == 403
    db = Session()
    try:
        assert db.get(BillingPayment, pid).status == "pending"
    finally:
        db.close()


def test_click_webhook_valid_and_duplicate(client, monkeypatch):
    api, Session = client
    from app.config import settings

    secret = "unit-test-click-secret"
    monkeypatch.setattr(settings, "click_secret", secret)
    _seed_owner(Session, username="wh_ok")
    _tok, _u, headers = _login(api, "wh_ok")
    pid, ref, cid = _create_pending_payment(api, headers, Session)
    body = _click_body(ref, secret)
    first = api.post("/api/billing/webhook/click", json=body)
    assert first.status_code == 200, first.text
    db = Session()
    try:
        company = db.get(Company, cid)
        until = company.paid_until
        assert db.get(BillingPayment, pid).status == "paid"
    finally:
        db.close()
    second = api.post("/api/billing/webhook/click", json=body)
    assert second.status_code == 200
    assert second.json().get("already") is True
    db = Session()
    try:
        assert db.get(Company, cid).paid_until == until
    finally:
        db.close()


def test_payme_webhook_fail_closed_and_valid(client, monkeypatch):
    api, Session = client
    from app.config import settings

    monkeypatch.setattr(settings, "payme_key", "")
    _seed_owner(Session, username="payme_a")
    _tok, _u, headers = _login(api, "payme_a")
    pid, ref, cid = _create_pending_payment(api, headers, Session)
    assert api.post("/api/billing/webhook/payme", json={"id": ref}).status_code == 503

    key = "unit-test-payme-key"
    merchant = "merchant-1"
    monkeypatch.setattr(settings, "payme_key", key)
    monkeypatch.setattr(settings, "payme_merchant_id", merchant)
    assert api.post("/api/billing/webhook/payme", json={"id": ref}).status_code == 401
    bad = base64.b64encode(b"wrong:creds").decode()
    assert (
        api.post(
            "/api/billing/webhook/payme",
            json={"id": ref},
            headers={"Authorization": f"Basic {bad}"},
        ).status_code
        == 403
    )
    good = base64.b64encode(f"{merchant}:{key}".encode()).decode()
    ok = api.post(
        "/api/billing/webhook/payme",
        json={"id": ref},
        headers={"Authorization": f"Basic {good}"},
    )
    assert ok.status_code == 200, ok.text
    db = Session()
    try:
        assert db.get(BillingPayment, pid).status == "paid"
        assert db.get(Company, cid).plan == "PRO"
    finally:
        db.close()


def test_product_patch_fields_do_not_bypass_ledger(client):
    api, Session = client
    _seed_owner(Session, username="stk_owner")
    _tok, _u, headers = _login(api, "stk_owner")
    created = api.post(
        "/api/products",
        headers=headers,
        json={
            "name": "Sut",
            "barcode": "7777777777777",
            "sku": "S1",
            "buy_price": 1000,
            "sell_price": 2000,
            "stock": 10,
            "min_stock": 2,
            "unit": "dona",
        },
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    assert created.json()["stock"] == 10

    same = api.patch(
        f"/api/products/{pid}",
        headers=headers,
        json={
            "name": "Sut yangi",
            "barcode": "7777777777777",
            "sku": "S1",
            "buy_price": 1100,
            "sell_price": 2200,
            "stock": 10,
            "min_stock": 3,
            "unit": "quti",
        },
    )
    assert same.status_code == 200, same.text
    assert same.json()["name"] == "Sut yangi"
    assert same.json()["sell_price"] == 2200
    assert same.json()["stock"] == 10
    assert same.json()["min_stock"] == 3
    assert same.json()["unit"] == "quti"

    db = Session()
    try:
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == pid).all()]
        assert kinds == ["OPENING"]
    finally:
        db.close()

    ignored = api.patch(
        f"/api/products/{pid}",
        headers=headers,
        json={
            "name": "Sut yangi",
            "barcode": "7777777777777",
            "sku": "S1",
            "buy_price": 1100,
            "sell_price": 2200,
            "stock": 15,
            "min_stock": 3,
            "unit": "quti",
        },
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["stock"] == 10
    adjusted = api.post(
        "/api/stock-adjustments",
        headers=headers,
        json={"product_id": pid, "qty": 5, "reason": "Physical count plus"},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["stock_after"] == 15
    db = Session()
    try:
        rows = db.query(StockMovement).filter(StockMovement.product_id == pid).order_by(StockMovement.id).all()
        assert [m.kind for m in rows] == ["OPENING", "ADJUST"]
        assert rows[-1].qty == 5
        assert rows[-1].balance_after == 15
        assert db.get(Product, pid).stock == 15
        actions = [a.action for a in db.query(AuditLog).filter(AuditLog.entity_id == pid).all()]
        assert "stock.adjust" in actions
        assert "product.stock.adjust" not in actions
    finally:
        db.close()


def test_product_patch_omitted_stock_unchanged(client):
    api, Session = client
    _seed_owner(Session, username="stk_omit")
    _tok, _u, headers = _login(api, "stk_omit")
    created = api.post(
        "/api/products",
        headers=headers,
        json={"name": "Non", "barcode": "8888888888888", "buy_price": 500, "sell_price": 800, "stock": 4},
    )
    pid = created.json()["id"]
    patched = api.patch(
        f"/api/products/{pid}",
        headers=headers,
        json={"name": "Non 2", "buy_price": 500, "sell_price": 900},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Non 2"
    assert patched.json()["stock"] == 4
    db = Session()
    try:
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == pid).all()]
        assert kinds == ["OPENING"]
    finally:
        db.close()


def test_product_patch_cross_company_forbidden(client):
    api, Session = client
    _seed_owner(Session, username="stk_a")
    _seed_owner(Session, username="stk_b", store_name="SB")
    _ta, _ua, ha = _login(api, "stk_a")
    _tb, _ub, hb = _login(api, "stk_b")
    prod = api.post(
        "/api/products",
        headers=ha,
        json={"name": "Secret", "barcode": "9999999999999", "buy_price": 1, "sell_price": 2, "stock": 9},
    )
    pid = prod.json()["id"]
    res = api.patch(
        f"/api/products/{pid}",
        headers=hb,
        json={"name": "stolen", "buy_price": 1, "sell_price": 2, "stock": 0},
    )
    assert res.status_code == 404
    db = Session()
    try:
        assert db.get(Product, pid).stock == 9
        assert db.get(Product, pid).name == "Secret"
    finally:
        db.close()


def test_production_secrets_fail_fast(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("PLATFORM_OWNER_PASSWORD", raising=False)
    monkeypatch.delenv("PLATFORM_OWNER_LOGIN", raising=False)

    missing = Settings(
        _env_file=None,
        node_env="production",
        jwt_secret="",
        platform_owner_password="unique-platform-pass-ok",
        platform_owner_login="platform",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_runtime_secrets(missing)

    insecure = Settings(
        _env_file=None,
        node_env="production",
        jwt_secret=JWT_DEV_PLACEHOLDER,
        platform_owner_password="unique-platform-pass-ok",
        platform_owner_login="platform",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_runtime_secrets(insecure)

    bad_pw = Settings(
        _env_file=None,
        node_env="production",
        jwt_secret="a" * 32,
        platform_owner_password=PLATFORM_DEV_PASSWORD_PLACEHOLDER,
        platform_owner_login="platform",
    )
    with pytest.raises(RuntimeError, match="PLATFORM_OWNER_PASSWORD"):
        validate_runtime_secrets(bad_pw)

    ok = Settings(
        _env_file=None,
        node_env="production",
        jwt_secret="a" * 32,
        platform_owner_password="unique-platform-pass-ok",
        platform_owner_login="platform",
    )
    validate_runtime_secrets(ok)

    dev = Settings(
        _env_file=None,
        node_env="development",
        jwt_secret=JWT_DEV_PLACEHOLDER,
        platform_owner_password=PLATFORM_DEV_PASSWORD_PLACEHOLDER,
        platform_owner_login="platform",
    )
    validate_runtime_secrets(dev)


def test_phase0_regression_core_endpoints(client):
    api, Session = client
    seed = _seed_owner(Session, username="reg_owner")
    _tok, user, headers = _login(api, "reg_owner")
    assert user["store_id"] == seed["store_id"]
    assert api.get("/api/auth/me", headers=headers).status_code == 200

    prod = api.post(
        "/api/products",
        headers=headers,
        json={"name": "Choy", "barcode": "1212121212128", "buy_price": 1000, "sell_price": 1500, "stock": 8},
    )
    assert prod.status_code == 200, prod.text
    pid = prod.json()["id"]

    sale = api.post(
        "/api/pos/sale",
        headers=headers,
        json={"items": [{"product_id": pid, "qty": 1}], "paid_cash": 1500, "payment_type": "CASH"},
    )
    assert sale.status_code == 200, sale.text

    cust = api.post(
        "/api/customers",
        headers=headers,
        json={"name": "Mijoz", "phone": "998901112233"},
    )
    assert cust.status_code == 200, cust.text
    assert api.get("/api/customers", headers=headers).status_code == 200
    assert api.get("/api/reports/dashboard", headers=headers).status_code == 200
    assert api.get("/api/billing", headers=headers).status_code == 200
    assert api.get("/api/ai/status", headers=headers).status_code == 200

    store_a = user["store_id"]
    patched = api.patch(
        f"/api/stores/{store_a}",
        headers=headers,
        json={"name": "A-Dokon", "username": "reg_store", "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    _st, _su, sh = _login(api, "reg_store")
    sin = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "Taminot", "note": "", "items": [{"product_id": pid, "qty": 2, "buy_price": 1000}]},
    )
    assert sin.status_code == 200, sin.text

    store_b = api.post(
        "/api/stores",
        headers=headers,
        json={"name": "B-Reg", "username": "reg_store_b", "password": "secret12"},
    ).json()["id"]
    xfer = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": store_a, "to_store_id": store_b, "items": [{"product_id": pid, "qty": 1}]},
    )
    assert xfer.status_code == 200, xfer.text
