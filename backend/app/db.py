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
        ("stores", "phone", "VARCHAR(80) DEFAULT ''"),
        ("sales", "customer_id", "INTEGER"),
        ("sales", "on_credit", "FLOAT DEFAULT 0"),
        ("sale_items", "buy_price", "FLOAT"),
    ]
    with engine.begin() as conn:
        for table, col, typ in extras:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            names = {r[1] for r in rows}
            if col not in names:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
