from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.clock import clock_block, period_range, snapshot_from_local
from app.ai.providers.base import ChatResult
from app.ai.service import chat, set_provider_override
from app.ai.tools import execute_tool
from app.db import Base
from app.models import Company, Store, User


def test_clock_today_is_tashkent_september_2026():
    snap = snapshot_from_local(datetime(2026, 9, 2, 21, 10, 0), tz_name="Asia/Tashkent", utc_offset="+05:00")
    assert snap["today"] == "2026-09-02"
    assert snap["timezone"] == "Asia/Tashkent"
    assert snap["utc_offset"] == "+05:00"
    assert snap["yesterday"] == "2026-09-01"
    assert snap["this_month_start"] == "2026-09-01"
    assert snap["this_month_end"] == "2026-09-30"
    assert snap["last_month_start"] == "2026-08-01"
    assert snap["last_month_end"] == "2026-08-31"


def test_clock_january_previous_is_december():
    snap = snapshot_from_local(datetime(2027, 1, 15, 12, 0, 0))
    assert snap["this_month_start"] == "2027-01-01"
    assert snap["this_month_end"] == "2027-01-31"
    assert snap["last_month_start"] == "2026-12-01"
    assert snap["last_month_end"] == "2026-12-31"


def test_clock_december_to_january():
    dec = snapshot_from_local(datetime(2026, 12, 31, 23, 0, 0))
    assert dec["this_month_start"] == "2026-12-01"
    assert dec["this_month_end"] == "2026-12-31"
    jan = snapshot_from_local(datetime(2027, 1, 1, 0, 5, 0))
    assert jan["this_month_start"] == "2027-01-01"
    assert jan["last_month_end"] == "2026-12-31"


def test_this_week_monday_start():
    # 2026-09-02 Wednesday → week Mon 2026-08-31 .. Sun 2026-09-06
    snap = snapshot_from_local(datetime(2026, 9, 2, 10, 0, 0))
    assert snap["this_week_start"] == "2026-08-31"
    assert snap["this_week_end"] == "2026-09-06"


def test_period_range_uses_server_clock():
    frozen = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
    with patch("app.ai.clock._instant", return_value=frozen):
        assert period_range(None, None, "today") == ("2026-09-02", "2026-09-02")
        assert period_range(None, None, "this_month") == ("2026-09-01", "2026-09-30")
        assert period_range(None, None, "last_month") == ("2026-08-01", "2026-08-31")
        assert period_range(None, None, "yesterday") == ("2026-09-01", "2026-09-01")


def test_period_range_january_rolls_to_previous_december():
    frozen = datetime(2027, 1, 15, 7, 0, tzinfo=timezone.utc)
    with patch("app.ai.clock._instant", return_value=frozen):
        assert period_range(None, None, "this_month") == ("2027-01-01", "2027-01-31")
        assert period_range(None, None, "last_month") == ("2026-12-01", "2026-12-31")


def test_clock_block_frozen_does_not_use_training_year():
    frozen = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)
    with patch("app.ai.clock._instant", return_value=frozen):
        text = clock_block()
    assert "today=2026-09-02" in text
    assert "this_month=2026-09-01..2026-09-30" in text
    assert "last_month=2026-08-01..2026-08-31" in text
    assert "Asia/Tashkent" in text
    assert "+05:00" in text
    assert "2023-10-26" not in text


@pytest.fixture
def clock_world():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    co = Company(name="A", plan="PRO", status="ACTIVE", currency="UZS", timezone="Asia/Tashkent")
    db.add(co)
    db.flush()
    st = Store(company_id=co.id, name="Do'kon A", is_active=True)
    db.add(st)
    db.flush()
    owner = User(
        company_id=co.id,
        store_id=st.id,
        full_name="Owner A",
        username="ownera",
        password_hash="x",
        role="OWNER",
        is_active=True,
    )
    db.add(owner)
    db.commit()
    uid = owner.id
    db.close()
    yield Session, uid
    set_provider_override(None)


def _user(Session, uid):
    s = Session()
    try:
        u = s.get(User, uid)
        s.expunge(u)
        return u
    finally:
        s.close()


def test_get_today_sales_date_from_clock(clock_world):
    Session, uid = clock_world
    frozen = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
    db = Session()
    with patch("app.ai.clock._instant", return_value=frozen):
        r = execute_tool("get_today_sales", {}, db, _user(Session, uid))
    db.close()
    assert r["ok"]
    assert r["data"]["date"] == "2026-09-02"
    assert r["data"]["timezone"] == "Asia/Tashkent"
    assert r["data"]["utc_offset"] == "+05:00"


def test_sales_period_this_and_last_month(clock_world):
    Session, uid = clock_world
    frozen = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
    db = Session()
    u = _user(Session, uid)
    with patch("app.ai.clock._instant", return_value=frozen):
        this_m = execute_tool("get_sales_summary", {"period": "this_month"}, db, u)
        last_m = execute_tool("get_sales_summary", {"period": "last_month"}, db, u)
    db.close()
    assert this_m["ok"]
    assert this_m["data"]["start_date"] == "2026-09-01"
    assert this_m["data"]["end_date"] == "2026-09-30"
    assert last_m["data"]["start_date"] == "2026-08-01"
    assert last_m["data"]["end_date"] == "2026-08-31"


def test_chat_prompt_contains_server_clock(clock_world):
    Session, uid = clock_world
    captured = []

    class Cap:
        name = "openai"
        model = "cap"

        def complete(self, messages, **kwargs):
            captured.extend(messages)
            return ChatResult(text="Bugungi sana CLOCK dagi qiymat.", provider="openai", model="cap")

    frozen = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
    set_provider_override(Cap())
    db = Session()
    try:
        with patch("app.ai.clock._instant", return_value=frozen):
            out = chat(db, _user(Session, uid), "Bugungi sana qaysi?", None)
    finally:
        db.close()
        set_provider_override(None)
    blob = "\n".join(str(m.get("content") or "") for m in captured)
    assert "CLOCK" in blob
    assert "2026-09-02" in blob
    assert "Asia/Tashkent" in blob
    assert "+05:00" in blob
    assert "2023-10-26" not in blob
    assert out["answer"]
