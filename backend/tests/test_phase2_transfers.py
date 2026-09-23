"""Phase 2 Step 5 — transfer / kirim quantity, isolation, atomicity."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Product, StockMovement, StockTransfer, Company, Store, User
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


def _store_headers(api, owner_headers, store_id, username):
    patched = api.patch(
        f"/api/stores/{store_id}",
        headers=owner_headers,
        json={"name": "A-Dokon", "username": username, "password": "secret12", "phone": "", "address": ""},
    )
    assert patched.status_code == 200, patched.text
    h, user = _login(api, username)
    return h, user


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


def test_transfer_normal_ledger_audit_history(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_ok")
    oh, _u = _login(api, "tr_ok")
    p = _product(api, oh, barcode="9100000000001", stock=10, sku="ST-TR")
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Dok", "username": "tr_ok_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    sh, su = _store_headers(api, oh, seed["store_id"], "tr_ok_a")
    xfer = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed["store_id"],
            "to_store_id": store_b.json()["id"],
            "note": "Filialga",
            "items": [{"product_id": p["id"], "qty": 4}],
        },
    )
    assert xfer.status_code == 200, xfer.text
    tid = xfer.json()["id"]
    left = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in left if x["id"] == p["id"]) == 6
    bh, _bu = _login(api, "tr_ok_b")
    dest_rows = api.get("/api/products", headers=bh).json()
    dest = next(x for x in dest_rows if x["barcode"] == "9100000000001")
    assert dest["stock"] == 4

    hist_src = api.get("/api/stock-movements", headers=sh, params={"product_id": p["id"], "kind": "TRANSFER_OUT"})
    assert hist_src.status_code == 200
    out = hist_src.json()
    assert len(out) == 1
    assert out[0]["qty"] == -4
    assert out[0]["balance_after"] == 6
    assert out[0]["ref_type"] == "transfer"
    assert out[0]["ref_id"] == tid
    assert out[0]["user_name"]
    assert "B-Dok" in (out[0].get("note") or "")

    hist_dst = api.get("/api/stock-movements", headers=bh, params={"kind": "TRANSFER_IN"})
    inn = hist_dst.json()
    assert inn and inn[0]["qty"] == 4
    assert inn[0]["ref_id"] == tid
    assert inn[0]["balance_after"] == 4

    detail = api.get(f"/api/transfers/{tid}", headers=sh)
    assert detail.status_code == 200
    assert detail.json()["from_store_id"] == seed["store_id"]
    assert detail.json()["to_store_id"] == store_b.json()["id"]
    assert detail.json()["items"][0]["qty"] == 4

    db = Session()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == "transfer.create", AuditLog.entity_id == tid).all()
        assert len(logs) == 1
        assert logs[0].user_id == su["id"]
        payload = logs[0].payload or ""
        assert str(seed["store_id"]) in payload
        assert str(store_b.json()["id"]) in payload
        movs = db.query(StockMovement).filter(StockMovement.ref_type == "transfer", StockMovement.ref_id == tid).all()
        kinds = {m.kind for m in movs}
        assert kinds == {"TRANSFER_OUT", "TRANSFER_IN"}
        assert db.get(Product, p["id"]).stock == 6
        assert db.query(StockTransfer).filter(StockTransfer.id == tid).one().company_id == seed["company_id"]
    finally:
        db.close()


def test_transfer_qty_zero_negative_malformed(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_qty")
    oh, _u = _login(api, "tr_qty")
    p = _product(api, oh, barcode="9100000000002", stock=10)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Q", "username": "tr_qty_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_qty_a")
    body = {"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 0}]}
    zero = api.post("/api/transfers", headers=sh, json=body)
    assert zero.status_code in (400, 422)
    neg = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": -2}]},
    )
    assert neg.status_code in (400, 422)
    bad = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": "abc"}]},
    )
    assert bad.status_code == 422
    nullq = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": None}]},
    )
    assert nullq.status_code in (400, 422)
    nan_headers = dict(sh)
    nan_headers["Content-Type"] = "application/json"
    nan = api.post(
        "/api/transfers",
        headers=nan_headers,
        content=(
            '{"from_store_id": %d, "to_store_id": %d, "items": [{"product_id": %d, "qty": NaN}]}'
            % (seed["store_id"], store_b, p["id"])
        ).encode("utf-8"),
    )
    assert nan.status_code in (400, 422)
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 10


def test_transfer_insufficient_stock(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_ins")
    oh, _u = _login(api, "tr_ins")
    p = _product(api, oh, barcode="9100000000003", stock=5)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-I", "username": "tr_ins_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_ins_a")
    res = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 6}]},
    )
    assert res.status_code == 400
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 5


def test_transfer_cross_company_and_unauthorized_store(client):
    api, Session = client
    seed_a = _seed_owner(Session, username="tr_coa")
    oh, _ua = _login(api, "tr_coa")
    p = _product(api, oh, barcode="9100000000004", stock=8)
    store_b_same = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-A", "username": "tr_coa_b", "password": "secret12"},
    ).json()["id"]
    seed_b = _seed_owner(Session, username="tr_cob", company_name="B Co")
    bh, _ub = _login(api, "tr_cob")
    store_b2 = api.post(
        "/api/stores",
        headers=bh,
        json={"name": "B2", "username": "tr_cob_2", "password": "secret12"},
    )
    assert store_b2.status_code == 200, store_b2.text
    shb, _sub = _store_headers(api, bh, seed_b["store_id"], "tr_cob_a")
    sh, _su = _store_headers(api, oh, seed_a["store_id"], "tr_coa_a")
    cross = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed_a["store_id"],
            "to_store_id": seed_b["store_id"],
            "items": [{"product_id": p["id"], "qty": 1}],
        },
    )
    assert cross.status_code == 400
    steal_prod = api.post(
        "/api/transfers",
        headers=shb,
        json={
            "from_store_id": seed_b["store_id"],
            "to_store_id": store_b2.json()["id"],
            "items": [{"product_id": p["id"], "qty": 1}],
        },
    )
    assert steal_prod.status_code == 404
    other_src = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": store_b_same,
            "to_store_id": seed_a["store_id"],
            "items": [{"product_id": p["id"], "qty": 1}],
        },
    )
    assert other_src.status_code == 403
    created = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed_a["store_id"],
            "to_store_id": store_b_same,
            "items": [{"product_id": p["id"], "qty": 1}],
        },
    )
    assert created.status_code == 200, created.text
    foreign_detail = api.get(f"/api/transfers/{created.json()['id']}", headers=bh)
    assert foreign_detail.status_code == 404
    assert api.get("/api/stores", headers=sh).status_code == 403
    opts = api.get("/api/transfer-stores", headers=sh)
    assert opts.status_code == 200
    ids = {s["id"] for s in opts.json()}
    assert seed_a["store_id"] in ids and seed_b["store_id"] not in ids


def test_transfer_cashier_forbidden_inactive_invalid(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_cash")
    oh, _u = _login(api, "tr_cash")
    p = _product(api, oh, barcode="9100000000005", stock=10)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-C", "username": "tr_cash_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_cash_a")
    cash = _staff(api, oh, username="tr_csh", role="CASHIER", store_id=seed["store_id"])
    denied = api.post(
        "/api/transfers",
        headers=cash,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 1}]},
    )
    assert denied.status_code == 403
    assert api.get("/api/transfer-stores", headers=cash).status_code == 403
    assert api.get("/api/transfers/1", headers=cash).status_code == 403
    missing = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": 999999, "qty": 1}]},
    )
    assert missing.status_code == 404
    api.post(f"/api/products/{p['id']}/toggle", headers=oh)
    inactive = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 1}]},
    )
    assert inactive.status_code == 400


def test_transfer_atomic_rollback_second_item_invalid(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_atom")
    oh, _u = _login(api, "tr_atom")
    p = _product(api, oh, barcode="9100000000006", stock=10)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-At", "username": "tr_atom_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_atom_a")
    res = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed["store_id"],
            "to_store_id": store_b,
            "items": [
                {"product_id": p["id"], "qty": 2},
                {"product_id": 999999, "qty": 1},
            ],
        },
    )
    assert res.status_code == 404
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 10
    db = Session()
    try:
        assert db.query(StockTransfer).count() == 0
        kinds = [m.kind for m in db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()]
        assert kinds == ["OPENING"]
    finally:
        db.close()


def test_transfer_duplicate_post_is_additive_until_stock_runs_out(client):
    """No sale-style idempotency_key on transfers; duplicate POST is a second movement."""
    api, Session = client
    seed = _seed_owner(Session, username="tr_dup")
    oh, _u = _login(api, "tr_dup")
    p = _product(api, oh, barcode="9100000000007", stock=10)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-D", "username": "tr_dup_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_dup_a")
    body = {
        "from_store_id": seed["store_id"],
        "to_store_id": store_b,
        "items": [{"product_id": p["id"], "qty": 4}],
    }
    a = api.post("/api/transfers", headers=sh, json=body)
    b = api.post("/api/transfers", headers=sh, json=body)
    assert a.status_code == 200 and b.status_code == 200
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 2
    c = api.post("/api/transfers", headers=sh, json=body)
    assert c.status_code == 400
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 2


def test_kirim_qty_must_be_positive(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_kirim")
    oh, _u = _login(api, "tr_kirim")
    p = _product(api, oh, barcode="9100000000008", stock=3)
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_kirim_a")
    zero = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "X", "items": [{"product_id": p["id"], "qty": 0, "buy_price": 1}]},
    )
    assert zero.status_code in (400, 422)
    neg = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "X", "items": [{"product_id": p["id"], "qty": -3, "buy_price": 1}]},
    )
    assert neg.status_code in (400, 422)
    ok = api.post(
        "/api/stock-ins",
        headers=sh,
        json={"supplier": "X", "items": [{"product_id": p["id"], "qty": 2, "buy_price": 8000}]},
    )
    assert ok.status_code == 200, ok.text
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 5


def test_transfer_inactive_source_or_destination_rejected(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_off")
    oh, _u = _login(api, "tr_off")
    p = _product(api, oh, barcode="9100000000009", stock=10)
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Off", "username": "tr_off_b", "password": "secret12"},
    ).json()["id"]
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_off_a")
    tog_dst = api.post(f"/api/stores/{store_b}/toggle", headers=oh)
    assert tog_dst.status_code == 200, tog_dst.text
    assert tog_dst.json()["is_active"] is False
    inactive_dst = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 1}]},
    )
    assert inactive_dst.status_code == 400
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 10
    tog_on = api.post(f"/api/stores/{store_b}/toggle", headers=oh)
    assert tog_on.status_code == 200
    assert tog_on.json()["is_active"] is True
    tog_src = api.post(f"/api/stores/{seed['store_id']}/toggle", headers=oh)
    assert tog_src.status_code == 200, tog_src.text
    assert tog_src.json()["is_active"] is False
    inactive_src = api.post(
        "/api/transfers",
        headers=sh,
        json={"from_store_id": seed["store_id"], "to_store_id": store_b, "items": [{"product_id": p["id"], "qty": 1}]},
    )
    assert inactive_src.status_code == 400
    listed = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in listed if x["id"] == p["id"]) == 10


def test_transfer_dest_lookup_sku_when_barcode_empty(client):
    api, Session = client
    seed = _seed_owner(Session, username="tr_skuf")
    oh, _u = _login(api, "tr_skuf")
    src = _product(api, oh, barcode="9100000000011", stock=10, sku="SKU-FALL", name="Src")
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Sku", "username": "tr_skuf_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    bh, _bu = _login(api, "tr_skuf_b")
    dest = _product(api, bh, barcode="9100000000012", stock=1, sku="SKU-FALL", name="Dest")
    db = Session()
    try:
        src_row = db.get(Product, src["id"])
        dest_row = db.get(Product, dest["id"])
        src_row.barcode = ""
        dest_row.barcode = ""
        db.commit()
    finally:
        db.close()
    sh, _su = _store_headers(api, oh, seed["store_id"], "tr_skuf_a")
    xfer = api.post(
        "/api/transfers",
        headers=sh,
        json={
            "from_store_id": seed["store_id"],
            "to_store_id": store_b.json()["id"],
            "items": [{"product_id": src["id"], "qty": 3}],
        },
    )
    assert xfer.status_code == 200, xfer.text
    dest_rows = api.get("/api/products", headers=bh).json()
    matches = [x for x in dest_rows if x["sku"] == "SKU-FALL"]
    assert len(matches) == 1
    assert matches[0]["id"] == dest["id"]
    assert matches[0]["stock"] == 4
    detail = api.get(f"/api/transfers/{xfer.json()['id']}", headers=sh)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["dest_product_id"] == dest["id"]
    left = api.get("/api/products", headers=sh).json()
    assert next(x["stock"] for x in left if x["id"] == src["id"]) == 7
