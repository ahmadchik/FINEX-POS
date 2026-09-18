import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import JWTError, jwt

from .config import settings

ROLES = ("OWNER", "ADMIN", "MANAGER", "CASHIER", "WAREHOUSE", "STORE")

ROLE_PERMS = {
    "OWNER": {"pos", "products", "stock", "cash", "reports", "staff", "settings", "customers", "stores", "suppliers", "billing"},
    "ADMIN": {"pos", "products", "stock", "cash", "reports", "staff", "settings", "customers", "stores", "suppliers", "billing"},
    "MANAGER": {"pos", "products", "stock", "cash", "reports", "customers", "suppliers"},
    "CASHIER": {"pos", "cash", "customers"},
    "WAREHOUSE": {"products", "stock", "suppliers"},
    "STORE": {"pos", "products", "stock", "cash", "reports", "customers", "suppliers"},
}

# In-memory, per-process only. Multi-instance production does not share counters.
# Do not trust X-Forwarded-For (trivial spoof). Callers must pass TCP peer / stable ids.
_rate: dict[str, list[float]] = {}
_MAX_KEY_LEN = 128
_MAX_BUCKETS = 20000


def _norm_rate_key(key: str) -> str:
    s = "".join(ch for ch in str(key or "") if ch.isprintable() and ch not in "\r\n")
    s = " ".join(s.split()).strip().lower()
    if not s:
        s = "unknown"
    if len(s) > _MAX_KEY_LEN:
        s = hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()[:40]
    return s


def client_host(request) -> str:
    host = request.client.host if request is not None and request.client else "x"
    return _norm_rate_key(host)


def rate_limit(key: str, limit: int = 8, window: int = 60) -> None:
    limit = max(int(limit or 1), 1)
    window = max(int(window or 1), 1)
    key = _norm_rate_key(key)
    now = time.time()
    hits = [t for t in _rate.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _rate[key] = hits
        raise HTTPException(429, "Juda ko'p urinish. Biroz kuting.")
    hits.append(now)
    _rate[key] = hits
    if len(_rate) > _MAX_BUCKETS:
        stale = [k for k, v in list(_rate.items()) if not v or now - v[-1] >= 3600]
        for k in stale:
            _rate.pop(k, None)
        if len(_rate) > _MAX_BUCKETS:
            oldest = sorted(_rate.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
            for k, _ in oldest[: max(1, len(_rate) - _MAX_BUCKETS)]:
                _rate.pop(k, None)


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


def create_token(user_id: int, company_id: int, role: str, store_id: int | None = None) -> str:
    payload = {
        "sub": str(user_id),
        "cid": company_id,
        "role": role,
        "sid": store_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_platform_token() -> str:
    payload = {
        "sub": "platform",
        "role": "PLATFORM",
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
