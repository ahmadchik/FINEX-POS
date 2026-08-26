from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_schema():
    Base.metadata.create_all(bind=engine)
    if not settings.database_url.startswith("sqlite"):
        return
    extras = [
        ("companies", "phone", "VARCHAR(80) DEFAULT ''"),
        ("companies", "address", "VARCHAR(300) DEFAULT ''"),
        ("companies", "inn", "VARCHAR(32) DEFAULT ''"),
        ("companies", "account_no", "INTEGER"),
        ("companies", "status", "VARCHAR(32) DEFAULT 'TRIAL'"),
        ("companies", "trial_ends_at", "DATETIME"),
        ("companies", "paid_until", "DATETIME"),
        ("companies", "currency", "VARCHAR(8) DEFAULT 'UZS'"),
        ("companies", "vat_percent", "FLOAT DEFAULT 0"),
        ("companies", "locale", "VARCHAR(8) DEFAULT 'uz'"),
        ("companies", "timezone", "VARCHAR(64) DEFAULT 'Asia/Tashkent'"),
        ("companies", "country", "VARCHAR(8) DEFAULT 'UZ'"),
        ("companies", "notes", "TEXT DEFAULT ''"),
        ("stores", "phone", "VARCHAR(80) DEFAULT ''"),
        ("stores", "is_active", "BOOLEAN DEFAULT 1"),
        ("sales", "customer_id", "INTEGER"),
        ("sales", "on_credit", "FLOAT DEFAULT 0"),
        ("sales", "tax_total", "FLOAT DEFAULT 0"),
        ("sales", "shift_id", "INTEGER"),
        ("sales", "idempotency_key", "VARCHAR(64)"),
        ("sale_items", "buy_price", "FLOAT"),
        ("sale_items", "tax", "FLOAT DEFAULT 0"),
        ("sale_items", "returned_qty", "FLOAT DEFAULT 0"),
        ("products", "vat_rate", "FLOAT"),
        ("customers", "email", "VARCHAR(160) DEFAULT ''"),
        ("customers", "credit_limit", "FLOAT DEFAULT 0"),
        ("customers", "is_active", "BOOLEAN DEFAULT 1"),
        ("stock_ins", "supplier_id", "INTEGER"),
    ]
    with engine.begin() as conn:
        for table, col, typ in extras:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            names = {r[1] for r in rows}
            if col not in names:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_account_no ON companies(account_no)"
        ))
        missing = conn.execute(text(
            "SELECT id FROM companies WHERE account_no IS NULL OR account_no = 0 ORDER BY id"
        )).fetchall()
        if missing:
            row = conn.execute(text("SELECT COALESCE(MAX(account_no), 100000) FROM companies")).fetchone()
            n = int(row[0] or 100000)
            if n < 100000:
                n = 100000
            for (cid,) in missing:
                n += 1
                conn.execute(text("UPDATE companies SET account_no = :n WHERE id = :id"), {"n": n, "id": cid})
        conn.execute(
            text(
                "UPDATE companies SET trial_ends_at = datetime(created_at, '+30 days') "
                "WHERE trial_ends_at IS NULL"
            )
        )
        conn.execute(
            text("UPDATE companies SET status = 'TRIAL' WHERE status IS NULL OR status = ''")
        )
        conn.execute(text("UPDATE stores SET is_active = 1 WHERE is_active IS NULL"))
        conn.execute(text("UPDATE customers SET is_active = 1 WHERE is_active IS NULL"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
