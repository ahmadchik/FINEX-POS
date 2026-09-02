from __future__ import annotations

import re

_SECRET = re.compile(
    r"(?i)(api[_-]?key|password|parol|secret|token|bearer|authorization|jwt_secret|payme_key|click_secret)\s*[:=]\s*\S+"
)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_INJECTION = re.compile(
    r"(?i)(ignore (previous|all) instructions|system prompt|you are now|reveal (the )?(secret|key|password))"
)

ALLOWED_PAGES = {
    "dashboard", "hisobotlar", "pos", "products", "stock", "transfers",
    "sales", "customers", "cash", "expenses", "suppliers", "stores",
    "staff", "settings", "login", "register", "home", "platform",
}

ALLOWED_ERROR_KEYS = ("status", "message", "path", "code")


def redact(text: str, limit: int = 2000) -> str:
    if not text:
        return ""
    out = _SECRET.sub("[redacted]", str(text))
    out = _JWT.sub("[redacted-token]", out)
    return out[:limit]


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


def safe_page(page: str | None) -> str:
    p = (page or "").strip().lower().split("?")[0]
    p = p.replace("#/app/", "").replace("#/", "").strip("/")
    if p in ALLOWED_PAGES:
        return p
    return ""


def safe_error(err: dict | None) -> dict:
    if not isinstance(err, dict):
        return {}
    out = {}
    if "status" in err:
        try:
            out["status"] = int(err["status"])
        except (TypeError, ValueError):
            pass
    msg = err.get("message") or err.get("detail") or ""
    if isinstance(msg, str):
        out["message"] = redact(msg, 300)
    path = err.get("path") or ""
    if isinstance(path, str) and path.startswith("/api/") and " " not in path:
        out["path"] = path[:120]
    return out


def safe_context(raw: dict | None, *, role: str, plan: str, status: str, writable: bool) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "page": safe_page(raw.get("page") or raw.get("module")),
        "role": (role or "")[:32],
        "plan": (plan or "")[:32],
        "company_status": (status or "")[:32],
        "writable": bool(writable),
        "last_error": safe_error(raw.get("last_error") or raw.get("error")),
    }
