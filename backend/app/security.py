import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from .config import settings

ROLES = ("OWNER", "ADMIN", "MANAGER", "CASHIER", "WAREHOUSE")

ROLE_PERMS = {
    "OWNER": {"pos", "products", "stock", "cash", "reports", "staff", "settings", "customers"},
    "ADMIN": {"pos", "products", "stock", "cash", "reports", "staff", "settings", "customers"},
    "MANAGER": {"pos", "products", "stock", "cash", "reports", "customers"},
    "CASHIER": {"pos", "cash", "customers"},
    "WAREHOUSE": {"products", "stock"},
}


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, 120_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(raw: str, hashed: str) -> bool:
    try:
        _, salt_hex, digest_hex = hashed.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, 120_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def create_token(user_id: int, company_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "cid": company_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def has_perm(role: str, perm: str) -> bool:
    return perm in ROLE_PERMS.get(role, set())
