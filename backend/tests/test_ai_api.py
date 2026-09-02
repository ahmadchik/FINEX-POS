from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.deps import get_current_user
from app.main import app
from app.models import Company, User


@pytest.fixture
def api_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(name="TestCo", plan="FREE", status="TRIAL")
    db.add(company)
    db.commit()
    owner = User(
        company_id=company.id,
        full_name="Owner",
        username="owner1",
        password_hash="x",
        role="OWNER",
        is_active=True,
    )
    cashier = User(
        company_id=company.id,
        full_name="Cash",
        username="cash1",
        password_hash="x",
        role="CASHIER",
        is_active=True,
    )
    db.add_all([owner, cashier])
    db.commit()
    ids = {"company": company.id, "owner": owner.id, "cashier": cashier.id}
    db.close()

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    current = {"role": "OWNER", "id": ids["owner"]}

    def override_user():
        return SimpleNamespace(
            id=current["id"],
            company_id=ids["company"],
            role=current["role"],
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    try:
        yield client, current, ids
    finally:
        app.dependency_overrides.clear()


def test_unauthorized_chat():
    app.dependency_overrides.clear()
    raw = TestClient(app)
    r = raw.post("/api/ai/chat", json={"message": "salom"})
    assert r.status_code == 401


def test_invalid_request(api_env):
    client, _, _ = api_env
    r = client.post("/api/ai/chat", json={"message": ""})
    assert r.status_code == 422


def test_user_question_kb_answer(api_env):
    client, _, _ = api_env
    r = client.post("/api/ai/chat", json={"message": "Yangi tovarni qanday qo'shaman?"})
    assert r.status_code == 200
    body = r.json()
    assert "Tovarlar" in body["answer"] or "tovar" in body["answer"].lower()
    assert body["fallback"] is True
    assert "api_key" not in body["answer"].lower()


def test_page_context(api_env):
    client, _, _ = api_env
    r = client.post(
        "/api/ai/chat",
        json={"message": "Bu yerda nima qilishim kerak?", "context": {"page": "pos"}},
    )
    assert r.status_code == 200
    assert "POS" in r.json()["answer"] or "smena" in r.json()["answer"].lower()
    assert r.json()["context_used"]["page"] == "pos"


def test_error_diagnosis(api_env):
    client, _, _ = api_env
    r = client.post(
        "/api/ai/chat",
        json={
            "message": "Sotuv amalga oshmadi",
            "context": {
                "page": "pos",
                "last_error": {"status": 400, "message": "Non: qoldiq yetarli emas (0)", "path": "/api/pos/sale"},
            },
        },
    )
    assert r.status_code == 200
    assert "qoldiq" in r.json()["answer"].lower() or "Kirim" in r.json()["answer"]


def test_cashier_can_ask(api_env):
    client, current, ids = api_env
    current["role"] = "CASHIER"
    current["id"] = ids["cashier"]
    r = client.post("/api/ai/chat", json={"message": "Sotuvni qanday qilaman?", "context": {"page": "pos"}})
    assert r.status_code == 200
    assert r.json()["context_used"]["role"] == "CASHIER"


def test_history_and_clear(api_env):
    client, _, _ = api_env
    client.post("/api/ai/chat", json={"message": "Hisobotni qanday chiqaraman?"})
    h = client.get("/api/ai/history")
    assert h.status_code == 200
    assert len(h.json()["messages"]) >= 2
    d = client.delete("/api/ai/history")
    assert d.status_code == 200
    h2 = client.get("/api/ai/history")
    assert h2.json()["messages"] == []


def test_report(api_env):
    client, _, _ = api_env
    r = client.post(
        "/api/ai/report",
        json={"question": "xato", "answer": "javob", "context": {"page": "pos"}},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_status_has_no_secrets(api_env):
    client, _, _ = api_env
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    raw = r.text.lower()
    assert "sk-" not in raw
    assert "api_key" not in raw
    assert r.json()["provider"] in ("fallback", "openai")
