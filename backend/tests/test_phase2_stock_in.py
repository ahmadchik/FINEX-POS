"""Phase 2 — Kirim (stock-in) idempotency, isolation, rollback."""

from datetime import datetime, timedelta
import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Product, StockIn, StockMovement, Company, Store, User
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
    return _login(api, username)


def _kirim(api, headers, *, product_id, qty=5, buy_price=8000, key=None, supplier="Vali"):
    body = {
        "supplier": supplier,
        "note": "Test kirim",
        "items": [{"product_id": product_id, "qty": qty, "buy_price": buy_price}],
    }
    if key is not None:
        body["idempotency_key"] = key
    return api.post("/api/stock-ins", headers=headers, json=body)


def _in_movements(Session, *, product_id=None, ref_id=None):
    db = Session()
    try:
        q = db.query(StockMovement).filter(StockMovement.kind == "IN", StockMovement.ref_type == "stock_in")
        if product_id is not None:
            q = q.filter(StockMovement.product_id == product_id)
        if ref_id is not None:
            q = q.filter(StockMovement.ref_id == ref_id)
        return q.all()
    finally:
        db.close()


def _audit(Session):
    db = Session()
    try:
        return db.query(AuditLog).filter(AuditLog.action == "stock.in.create").all()
    finally:
        db.close()


def _stock(Session, product_id):
    db = Session()
    try:
        return float(db.get(Product, product_id).stock or 0)
    finally:
        db.close()


def test_kirim_normal_increases_stock_once(client):
    api, Session = client
    seed = _seed_owner(Session, username="ki_ok")
    oh, _u = _login(api, "ki_ok")
    p = _product(api, oh, barcode="9200000000001", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "ki_ok_st")
    res = _kirim(api, sh, product_id=p["id"], qty=5, key="kirim-ok-1")
    assert res.status_code == 200, res.text
    assert res.json()["number"]
    assert _stock(Session, p["id"]) == 15
    assert len(_in_movements(Session, product_id=p["id"])) == 1
    assert len(_audit(Session)) == 1
    db = Session()
    try:
        assert db.query(StockIn).count() == 1
        assert db.query(StockIn).one().idempotency_key == "kirim-ok-1"
    finally:
        db.close()


def test_kirim_duplicate_key_replays_same_document(client):
    api, Session = client
    seed = _seed_owner(Session, username="ki_dup")
    oh, _u = _login(api, "ki_dup")
    p = _product(api, oh, barcode="9200000000002", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "ki_dup_st")
    body_key = "kirim-same"
    a = _kirim(api, sh, product_id=p["id"], qty=5, key=body_key)
    b = _kirim(api, sh, product_id=p["id"], qty=5, key=body_key)
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert a.json()["id"] == b.json()["id"]
    assert a.json()["number"] == b.json()["number"]
    assert _stock(Session, p["id"]) == 15
    assert len(_in_movements(Session, product_id=p["id"])) == 1
    assert len(_audit(Session)) == 1
    db = Session()
    try:
        assert db.query(StockIn).count() == 1
    finally:
        db.close()


def test_kirim_different_keys_are_separate(client):
    api, Session = client
    seed = _seed_owner(Session, username="ki_keys")
    oh, _u = _login(api, "ki_keys")
    p = _product(api, oh, barcode="9200000000003", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "ki_keys_st")
    a = _kirim(api, sh, product_id=p["id"], qty=3, key="kirim-a")
    b = _kirim(api, sh, product_id=p["id"], qty=4, key="kirim-b")
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] != b.json()["id"]
    assert _stock(Session, p["id"]) == 17
    assert len(_in_movements(Session, product_id=p["id"])) == 2
    assert len(_audit(Session)) == 2


def test_kirim_without_key_remains_additive(client):
    api, Session = client
    seed = _seed_owner(Session, username="ki_nokey")
    oh, _u = _login(api, "ki_nokey")
    p = _product(api, oh, barcode="9200000000004", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "ki_nokey_st")
    a = _kirim(api, sh, product_id=p["id"], qty=2)
    b = _kirim(api, sh, product_id=p["id"], qty=2)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] != b.json()["id"]
    assert _stock(Session, p["id"]) == 14


def test_kirim_key_isolated_by_company_and_store(client):
    api, Session = client
    seed_a = _seed_owner(Session, username="ki_coa")
    oh, _ua = _login(api, "ki_coa")
    pa = _product(api, oh, barcode="9200000000005", stock=10)
    sha, _ = _store_headers(api, oh, seed_a["store_id"], "ki_coa_st")
    store_b = api.post(
        "/api/stores",
        headers=oh,
        json={"name": "B-Ki", "username": "ki_coa_b", "password": "secret12"},
    )
    assert store_b.status_code == 200, store_b.text
    seed_c = _seed_owner(Session, username="ki_cob", company_name="B Co")
    ohc, _uc = _login(api, "ki_cob")
    pc = _product(api, ohc, barcode="9200000000005", stock=8)
    shc, _ = _store_headers(api, ohc, seed_c["store_id"], "ki_cob_st")
    key = "shared-kirim-key"
    a = _kirim(api, sha, product_id=pa["id"], qty=1, key=key)
    bh, _ = _login(api, "ki_coa_b")
    pb = _product(api, bh, barcode="9200000000006", stock=3, name="B sut")
    b = _kirim(api, bh, product_id=pb["id"], qty=1, key=key)
    c = _kirim(api, shc, product_id=pc["id"], qty=1, key=key)
    assert a.status_code == 200 and b.status_code == 200 and c.status_code == 200
    assert len({a.json()["id"], b.json()["id"], c.json()["id"]}) == 3
    assert _stock(Session, pa["id"]) == 11
    assert _stock(Session, pb["id"]) == 4
    assert _stock(Session, pc["id"]) == 9


def test_kirim_rollback_invalid_second_item(client):
    api, Session = client
    seed = _seed_owner(Session, username="ki_rb")
    oh, _u = _login(api, "ki_rb")
    p = _product(api, oh, barcode="9200000000007", stock=10)
    sh, _su = _store_headers(api, oh, seed["store_id"], "ki_rb_st")
    res = api.post(
        "/api/stock-ins",
        headers=sh,
        json={
            "supplier": "X",
            "idempotency_key": "kirim-rb",
            "items": [
                {"product_id": p["id"], "qty": 2, "buy_price": 8000},
                {"product_id": 999999, "qty": 1, "buy_price": 1},
            ],
        },
    )
    assert res.status_code == 404, res.text
    assert _stock(Session, p["id"]) == 10
    assert _in_movements(Session, product_id=p["id"]) == []
    assert _audit(Session) == []
    db = Session()
    try:
        assert db.query(StockIn).count() == 0
    finally:
        db.close()


def test_kirim_idempotency_index_exists(client):
    api, Session = client
    _seed_owner(Session, username="ki_idx")
    db = Session()
    try:
        bind = db.get_bind()
        rows = bind.connect().execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='index' "
                "AND name = 'uq_stock_ins_company_store_idempotency'"
            )
        ).fetchall()
        assert rows
        sql = rows[0][1] or ""
        assert "company_id" in sql and "store_id" in sql and "idempotency_key" in sql
    finally:
        db.close()


def test_app_js_kirim_sends_idempotency_key():
    js_path = os.path.join(os.path.dirname(__file__), "..", "app", "web", "assets", "app.js")
    with open(js_path, encoding="utf-8") as fh:
        js = fh.read()
    submit = js.find("inForm.onsubmit")
    assert submit != -1
    idem = js.find("idempotency_key", submit)
    busy = js.find("__stockBusy", submit)
    post = js.find("/api/stock-ins", submit)
    assert idem != -1 and busy != -1 and post != -1
    assert busy < post
    assert idem < js.find("render();", submit)


def test_kirim_concurrent_same_key_one_movement(tmp_path):
    import httpx

    _rate.clear()
    db_path = tmp_path / "kirim_race.db"
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
        seed = _seed_owner(Session, username="ki_race")
        oh, _u = _login(api, "ki_race")
        p = _product(api, oh, barcode="9200000000008", stock=10)
        sh, _su = _store_headers(api, oh, seed["store_id"], "ki_race_st")
        pid = p["id"]
        headers = {k: v for k, v in sh.items()}
        payload = {
            "supplier": "Race",
            "idempotency_key": "kirim-race",
            "items": [{"product_id": pid, "qty": 6, "buy_price": 8000}],
        }

        async def _race():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                return await asyncio.gather(
                    ac.post("/api/stock-ins", headers=headers, json=payload),
                    ac.post("/api/stock-ins", headers=headers, json=payload),
                )

        r1, r2 = asyncio.run(_race())
        assert r1.status_code == 200 and r2.status_code == 200, (r1.status_code, r1.text, r2.status_code, r2.text)
        assert r1.json()["id"] == r2.json()["id"]
        assert _stock(Session, pid) == 16
        assert len(_in_movements(Session, product_id=pid)) == 1
        assert len(_audit(Session)) == 1
        db = Session()
        try:
            assert db.query(StockIn).count() == 1
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()
        _rate.clear()
