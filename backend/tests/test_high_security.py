"""HIGH security hardening tests. Isolated in-memory SQLite."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import (
    PLATFORM_DEV_PASSWORD_PLACEHOLDER,
    Settings,
    cors_origin_list,
    settings,
    validate_runtime_secrets,
)
from app.db import Base, get_db
from app.main import app
from app.models import Company, User
from app.security import _rate, client_host, create_token, hash_password, rate_limit


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


def _seed_owner(Session, *, username, password="secret12", plan="VIP", status="ACTIVE"):
    db = Session()
    try:
        from app.models import Store

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


def test_cors_origin_list_never_star():
    dev = Settings(_env_file=None, node_env="development", cors_origins="")
    origins = cors_origin_list(dev)
    assert "*" not in origins
    assert "http://127.0.0.1:8001" in origins

    prod_empty = Settings(
        _env_file=None,
        node_env="production",
        cors_origins="",
        jwt_secret="a" * 32,
        platform_owner_password="unique-platform-pass-ok",
    )
    assert cors_origin_list(prod_empty) == []

    prod_explicit = Settings(
        _env_file=None,
        node_env="production",
        cors_origins="https://fixen.uz",
        jwt_secret="a" * 32,
        platform_owner_password="unique-platform-pass-ok",
    )
    assert cors_origin_list(prod_explicit) == ["https://fixen.uz"]


def test_production_cors_wildcard_fail_fast(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("PLATFORM_OWNER_PASSWORD", raising=False)
    cfg = Settings(
        _env_file=None,
        node_env="production",
        jwt_secret="a" * 32,
        platform_owner_password="unique-platform-pass-ok",
        platform_owner_login="platform",
        cors_origins="*",
    )
    with pytest.raises(RuntimeError, match="CORS"):
        validate_runtime_secrets(cfg)


def test_cors_allowed_and_disallowed_origin(client):
    api, _Session = client
    allowed = cors_origin_list(settings)
    assert allowed
    origin = allowed[0]
    ok = api.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == origin
    assert ok.headers.get("access-control-allow-credentials") == "true"

    bad = api.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.headers.get("access-control-allow-origin") != "https://evil.example"


def test_rate_limit_normalizes_and_enforces():
    _rate.clear()
    for _ in range(3):
        rate_limit("login:1.2.3.4:user", 3, 60)
    with pytest.raises(Exception) as exc:
        rate_limit("LOGIN:1.2.3.4:USER", 3, 60)
    assert getattr(exc.value, "status_code", None) == 429
    _rate.clear()
    rate_limit("k:" + ("x" * 5000), 1, 60)
    assert all(len(k) <= 128 for k in _rate)


def test_login_rate_limit_not_bypassed_by_case(client):
    api, Session = client
    _seed_owner(Session, username="rateuser")
    for _ in range(8):
        res = api.post("/api/auth/login", json={"username": "RateUser", "password": "wrongpw"})
        assert res.status_code == 401
    blocked = api.post("/api/auth/login", json={"username": "rateuser", "password": "wrongpw"})
    assert blocked.status_code == 429
    _rate.clear()
    ok = api.post("/api/auth/login", json={"username": "rateuser", "password": "secret12"})
    assert ok.status_code == 200


def test_platform_reset_password_not_in_response(client):
    api, Session = client
    seed = _seed_owner(Session, username="rst_owner")
    plat = api.post(
        "/api/platform/login",
        json={
            "username": settings.platform_owner_login,
            "password": settings.platform_owner_password,
        },
    )
    assert plat.status_code == 200, plat.text
    ph = {"Authorization": f"Bearer {plat.json()['access']}"}
    missing = api.post(
        f"/api/platform/companies/{seed['company_id']}/reset-password",
        headers=ph,
        json={},
    )
    assert missing.status_code == 400
    new_pw = "NewPass99"
    res = api.post(
        f"/api/platform/companies/{seed['company_id']}/reset-password",
        headers=ph,
        json={"password": new_pw},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    blob = str(data).lower()
    assert "password" not in data
    assert new_pw.lower() not in blob
    assert PLATFORM_DEV_PASSWORD_PLACEHOLDER not in blob
    assert data.get("ok") is True
    assert data.get("username") == "rst_owner"
    old = api.post("/api/auth/login", json={"username": "rst_owner", "password": "secret12"})
    assert old.status_code == 401
    ok = api.post("/api/auth/login", json={"username": "rst_owner", "password": new_pw})
    assert ok.status_code == 200


def test_jwt_cid_matches_database(client):
    api, Session = client
    seed = _seed_owner(Session, username="cid_ok")
    token, user, headers = _login(api, "cid_ok")
    me = api.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["company_id"] == seed["company_id"]

    other = _seed_owner(Session, username="cid_other")
    forged = jwt.encode(
        {
            "sub": str(seed["user_id"]),
            "cid": other["company_id"],
            "role": "OWNER",
            "sid": seed["store_id"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_alg,
    )
    bad = api.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert bad.status_code == 401

    db = Session()
    try:
        u = db.get(User, seed["user_id"])
        u.company_id = other["company_id"]
        db.commit()
    finally:
        db.close()
    stale = api.get("/api/auth/me", headers=headers)
    assert stale.status_code == 401


def test_jwt_inactive_user_and_suspended_company(client):
    api, Session = client
    seed = _seed_owner(Session, username="cid_off")
    token, _u, headers = _login(api, "cid_off")
    db = Session()
    try:
        db.get(User, seed["user_id"]).is_active = False
        db.commit()
    finally:
        db.close()
    assert api.get("/api/auth/me", headers=headers).status_code == 401

    seed2 = _seed_owner(Session, username="cid_sus")
    _t2, _u2, h2 = _login(api, "cid_sus")
    db = Session()
    try:
        db.get(Company, seed2["company_id"]).status = "SUSPENDED"
        db.commit()
    finally:
        db.close()
    assert api.get("/api/auth/me", headers=h2).status_code == 403


def test_jwt_expired_rejected(client):
    api, Session = client
    seed = _seed_owner(Session, username="cid_exp")
    expired = jwt.encode(
        {
            "sub": str(seed["user_id"]),
            "cid": seed["company_id"],
            "role": "OWNER",
            "sid": seed["store_id"],
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_alg,
    )
    res = api.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_jwt_cross_company_resource_rejected(client):
    api, Session = client
    _seed_owner(Session, username="iso_a")
    _seed_owner(Session, username="iso_b")
    _ta, ua, ha = _login(api, "iso_a")
    _tb, _ub, hb = _login(api, "iso_b")
    prod = api.post(
        "/api/products",
        headers=ha,
        json={"name": "Secret", "barcode": "1010101010104", "buy_price": 1, "sell_price": 2, "stock": 1},
    )
    assert prod.status_code == 200, prod.text
    pid = prod.json()["id"]
    assert api.get(f"/api/products", headers=hb).status_code == 200
    assert all(p["id"] != pid for p in api.get("/api/products", headers=hb).json())
    assert api.patch(
        f"/api/products/{pid}",
        headers=hb,
        json={"name": "stolen", "buy_price": 1, "sell_price": 2, "stock": 0},
    ).status_code == 404
