"""Whitelisted read-only tools. The model never sees SQL or tenant ids."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import User
from ..security import has_perm
from . import queries

log = logging.getLogger("finex.ai")

MAX_TOOL_ROUNDS = 2
FORBIDDEN_ARG_KEYS = {"company_id", "store_id", "company", "store", "cid", "sid", "sql", "query_sql"}

TOOL_PERMS: dict[str, tuple[str, ...]] = {
    "get_today_sales": ("reports",),
    "get_top_selling_products": ("reports",),
    "get_low_stock_products": ("products", "reports"),
    "get_inventory_summary": ("products",),
    "get_product_stock": ("products",),
    "get_sales_summary": ("reports",),
    "get_profit_summary": ("reports",),
}

OPENAI_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_today_sales",
            "description": "Bugungi savdo. Sana server CLOCK (Asia/Tashkent) dan. Model yilini ishlatmang.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_selling_products",
            "description": "Eng ko'p sotilgan tovarlar. Sana berilmasa oxirgi 7 kun (dashboard kabi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    "period": {
                        "type": "string",
                        "enum": ["today", "yesterday", "this_week", "this_month", "last_month"],
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD, ixtiyoriy"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD, ixtiyoriy"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_products",
            "description": "min_stock dan past yoki teng qoldiq (tugash arafasi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_summary",
            "description": "Ombor: faol SKU soni, jami qoldiq, tannarx bo'yicha qiymat.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_stock",
            "description": "Tovarni nom, barcode yoki SKU bo'yicha qidirib qoldiqni qaytaradi. SQL emas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 80},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sales_summary",
            "description": "Savdo jami. Relativ davr uchun period=this_month|last_month|today|yesterday|this_week (server CLOCK). Yoki start_date+end_date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "yesterday", "this_week", "this_month", "last_month"],
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_profit_summary",
            "description": "Yalpi foyda (dashboard formulasi). period yoki start_date+end_date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "yesterday", "this_week", "this_month", "last_month"],
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "additionalProperties": False,
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in OPENAI_TOOLS}


def _ok(data: dict) -> dict:
    return {"ok": True, "error": None, "data": data}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "error": code, "message": message, "data": None}


def _strip_args(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k not in FORBIDDEN_ARG_KEYS}


def _int_limit(value: Any, *, default: int, lo: int = 1, hi: int = 20) -> int:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit butun son bo'lishi kerak") from exc
    if n < lo or n > hi:
        raise ValueError(f"limit {lo}–{hi} oralig'ida bo'lsin")
    return n


def _need_perm(user: User, name: str) -> dict | None:
    perms = TOOL_PERMS.get(name) or ()
    if any(has_perm(user.role, p) for p in perms):
        return None
    return _err("permission_denied", "Sizda bu ma'lumotni ko'rish uchun ruxsat mavjud emas.")


def _run_today_sales(db: Session, user: User, args: dict) -> dict:
    return _ok(queries.get_today_sales(db, user))


def _run_top(db: Session, user: User, args: dict) -> dict:
    limit = _int_limit(args.get("limit"), default=5)
    period = args.get("period") or None
    start = args.get("start_date") or None
    end = args.get("end_date") or None
    if period:
        from .clock import period_range

        start, end = period_range(db, user, str(period))
    elif bool(start) != bool(end):
        raise ValueError("start_date va end_date birga berilsin")
    return _ok(
        queries.get_top_selling_products(
            db, user, limit=limit, start_date=start, end_date=end
        )
    )


def _run_low(db: Session, user: User, args: dict) -> dict:
    limit = _int_limit(args.get("limit"), default=8)
    return _ok(queries.get_low_stock_products(db, user, limit=limit))


def _run_inventory(db: Session, user: User, args: dict) -> dict:
    return _ok(queries.get_inventory_summary(db, user))


def _run_product_stock(db: Session, user: User, args: dict) -> dict:
    q = str(args.get("query") or "").strip()
    if not q:
        raise ValueError("query majburiy")
    if len(q) > 80:
        raise ValueError("query juda uzun")
    return _ok(queries.get_product_stock(db, user, q))


def _run_sales(db: Session, user: User, args: dict) -> dict:
    return _ok(
        queries.get_sales_summary(
            db,
            user,
            args.get("start_date"),
            args.get("end_date"),
            period=args.get("period"),
        )
    )


def _run_profit(db: Session, user: User, args: dict) -> dict:
    return _ok(
        queries.get_profit_summary(
            db,
            user,
            args.get("start_date"),
            args.get("end_date"),
            period=args.get("period"),
        )
    )


HANDLERS: dict[str, Callable[[Session, User, dict], dict]] = {
    "get_today_sales": _run_today_sales,
    "get_top_selling_products": _run_top,
    "get_low_stock_products": _run_low,
    "get_inventory_summary": _run_inventory,
    "get_product_stock": _run_product_stock,
    "get_sales_summary": _run_sales,
    "get_profit_summary": _run_profit,
}


def execute_tool(name: str, arguments: Any, db: Session, user: User) -> dict:
    t0 = time.perf_counter()
    ok = False
    code = "ok"
    try:
        if name not in TOOL_NAMES or name not in HANDLERS:
            result = _err("unknown_tool", "Bu so'rov uchun ruxsat etilgan tool yo'q.")
        else:
            denied = _need_perm(user, name)
            if denied:
                result = denied
            else:
                result = HANDLERS[name](db, user, _strip_args(arguments))
        ok = bool(result.get("ok"))
        code = result.get("error") or "ok"
        return result
    except HTTPException as exc:
        code = "store_not_found" if exc.status_code == 400 else "http_error"
        return _err(code, str(exc.detail) if exc.detail else "So'rov bajarilmadi.")
    except ValueError as exc:
        code = "invalid_arguments"
        return _err("invalid_arguments", str(exc))
    except Exception:
        code = "tool_error"
        log.warning("ai.tool_exc name=%s user=%s", name, getattr(user, "id", None), exc_info=True)
        return _err("tool_error", "Ma'lumotni olishda xatolik. Raqam o'ylab topilmaydi.")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("ai.tool name=%s ok=%s code=%s ms=%s user=%s", name, ok, code, ms, getattr(user, "id", None))


def execute_openai_tool_call(call: dict, db: Session, user: User) -> dict:
    fn = call.get("function") if isinstance(call, dict) else None
    if isinstance(fn, dict):
        name = str(fn.get("name") or "")
        raw = fn.get("arguments") or "{}"
    else:
        name = str((call or {}).get("name") or "")
        raw = (call or {}).get("arguments") or "{}"
    if isinstance(raw, dict):
        args = raw
    else:
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return _err("invalid_arguments", "Tool argumentlari JSON emas.")
    if not isinstance(args, dict):
        return _err("invalid_arguments", "Tool argumentlari obyekt bo'lishi kerak.")
    return execute_tool(name, args, db, user)
