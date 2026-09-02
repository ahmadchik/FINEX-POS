from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.knowledge import retrieve
from app.ai.providers.base import ChatResult
from app.ai.service import set_provider_override
from app.db import Base, get_db
from app.deps import get_current_user
from app.main import app
from app.models import Company, User

QUESTIONS = [
    ("Товарни қандай қўшаман?", "products-add", "Tovarlar"),
    ("Кассани қандай очаман?", "pos-shift", "Smena"),
    ("Нега товар сотилмаяпти?", "pos-sale", "POS"),
    ("Қарзга савдони қандай қиламан?", "pos-sale", "Qarz"),
    ("Штрих-кодни қандай киритаман?", "products-barcode", "Barcode"),
    ("Касса сменасини қандай ёпаман?", "pos-shift", "yop"),
]


class FakeModel:
    name = "openai"
    model = "fake-test"
    calls: list[list[dict]] = []

    def complete(self, messages, *, max_tokens, temperature, timeout):
        FakeModel.calls.append(messages)
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        kb = next((m["content"] for m in messages if "### " in m.get("content", "")), "")
        title = ""
        if "### " in kb:
            title = kb.split("### ", 1)[1].split("\n", 1)[0]
        # Simulate a model: answer the asked question using only the provided context title.
        text = f"Savol: {user}\nMavzu: {title}. Faqat shu haqida: {kb[len('Quyidagi'):800][:280]}"
        return ChatResult(text=text, provider="openai", model="fake-test", latency_ms=1)


@pytest.fixture
def api():
    FakeModel.calls = []
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(name="T", plan="FREE", status="TRIAL")
    db.add(company)
    db.commit()
    owner = User(company_id=company.id, full_name="O", username="ow", password_hash="x", role="OWNER", is_active=True)
    db.add(owner)
    db.commit()
    uid, cid = owner.id, company.id
    db.close()

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    def override_user():
        return SimpleNamespace(id=uid, company_id=cid, role="OWNER", is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    set_provider_override(FakeModel())
    client = TestClient(app)
    try:
        yield client
    finally:
        set_provider_override(None)
        app.dependency_overrides.clear()


@pytest.mark.parametrize("question,expect_id,_hint", QUESTIONS)
def test_retrieve_picks_specific_article(question, expect_id, _hint):
    ids = [a["id"] for a in retrieve(question, limit=2)]
    assert expect_id in ids
    assert len(ids) <= 2


def test_without_model_returns_503():
    set_provider_override(None)
    # no override, empty API key
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    c = Company(name="T", plan="FREE", status="TRIAL")
    db.add(c)
    db.commit()
    u = User(company_id=c.id, full_name="O", username="u2", password_hash="x", role="OWNER", is_active=True)
    db.add(u)
    db.commit()
    uid, cid = u.id, c.id
    db.close()

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uid, company_id=cid, role="OWNER", is_active=True)
    try:
        r = TestClient(app).post("/api/ai/chat", json={"message": "Товарни қандай қўшаман?"})
        assert r.status_code == 503
        assert "Knowledge Base" in r.json()["detail"] or "AI_API_KEY" in r.json()["detail"] or "ulanmagan" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_model_receives_user_question_not_full_kb_dump(api):
    r = api.post("/api/ai/chat", json={"message": "Штрих-кодни қандай киритаман?"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is False
    assert body["provider"] == "openai"
    assert "Штрих" in body["answer"] or "shtrix" in body["answer"].lower() or "Barcode" in body["answer"]
    # must not paste all four modules
    assert not (
        "Kirim" in body["answer"] and "Smena" in body["answer"] and "Barcode" in body["answer"] and "POS" in body["answer"]
    )
    last = FakeModel.calls[-1]
    user = next(m["content"] for m in reversed(last) if m["role"] == "user")
    assert "Штрих-кодни" in user or "shtrix" in user.lower()
    sys_all = "\n".join(m["content"] for m in last if m["role"] == "system")
    assert "to'liq javob emas" in sys_all or "kontekst" in sys_all.lower() or "kontekst" in sys_all


def test_six_questions_distinct_answers(api):
    answers = []
    for q, _id, hint in QUESTIONS:
        FakeModel.calls = []
        r = api.post("/api/ai/chat", json={"message": q, "context": {"page": "dashboard"}})
        assert r.status_code == 200, r.text
        ans = r.json()["answer"]
        answers.append(ans)
        assert hint.lower() in ans.lower() or q[:8] in ans
        assert r.json()["kb_ids"][0] in (_id, r.json()["kb_ids"][0])
    assert len(set(answers)) == len(answers)


def test_followup_uses_history(api):
    api.post("/api/ai/chat", json={"message": "Товарни қандай қўшаман?"})
    r = api.post("/api/ai/chat", json={"message": "Штрих-кодчи?"})
    assert r.status_code == 200
    last = FakeModel.calls[-1]
    roles = [m["role"] for m in last if m["role"] in ("user", "assistant")]
    assert roles.count("user") >= 2
