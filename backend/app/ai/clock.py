"""Authoritative calendar clock for AI. Models must not invent the current date."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone, date

DEFAULT_TZ = "Asia/Tashkent"
PERIODS = ("today", "yesterday", "this_week", "this_month", "last_month")


def _tz(name: str | None):
    raw = (name or "").strip() or DEFAULT_TZ
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(raw), raw
    except Exception:
        pass
    return timezone(timedelta(hours=5)), DEFAULT_TZ


def _instant() -> datetime:
    return datetime.now(timezone.utc)


def tz_name_for(db=None, user=None) -> str:
    if db is None or user is None:
        return DEFAULT_TZ
    try:
        from ..models import Company

        company = db.get(Company, user.company_id)
        name = (getattr(company, "timezone", None) or "").strip()
        if name:
            _, canonical = _tz(name)
            return name if canonical else DEFAULT_TZ
    except Exception:
        pass
    return DEFAULT_TZ


def now_local(db=None, user=None) -> datetime:
    """Naive local datetime in company timezone (default Asia/Tashkent)."""
    zone, _ = _tz(tz_name_for(db, user))
    return _instant().astimezone(zone).replace(tzinfo=None)


def utc_offset_label(db=None, user=None) -> str:
    zone, _ = _tz(tz_name_for(db, user))
    delta = _instant().astimezone(zone).utcoffset() or timedelta(hours=5)
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def _month_end(d: date) -> date:
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def _prev_month_start(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


def snapshot_from_local(now: datetime, tz_name: str = DEFAULT_TZ, utc_offset: str = "+05:00") -> dict:
    today = now.date() if isinstance(now, datetime) else now
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = date(today.year, today.month, 1)
    month_end = _month_end(today)
    prev_start = _prev_month_start(month_start)
    prev_end = _month_end(prev_start)
    return {
        "timezone": tz_name or DEFAULT_TZ,
        "utc_offset": utc_offset,
        "now": now.strftime("%Y-%m-%d %H:%M:%S") if isinstance(now, datetime) else f"{today.isoformat()} 00:00:00",
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "this_week_start": week_start.isoformat(),
        "this_week_end": week_end.isoformat(),
        "this_month_start": month_start.isoformat(),
        "this_month_end": month_end.isoformat(),
        "last_month_start": prev_start.isoformat(),
        "last_month_end": prev_end.isoformat(),
        "weekday": now.strftime("%A") if isinstance(now, datetime) else today.strftime("%A"),
    }


def snapshot(db=None, user=None) -> dict:
    now = now_local(db, user)
    return snapshot_from_local(now, tz_name_for(db, user), utc_offset_label(db, user))


def clock_block(db=None, user=None) -> str:
    s = snapshot(db, user)
    return (
        "CLOCK (server — authoritative. Do not use training-data dates like 2023.)\n"
        f"timezone={s['timezone']} utc_offset={s['utc_offset']}\n"
        f"now={s['now']}\n"
        f"today={s['today']} yesterday={s['yesterday']} weekday={s['weekday']}\n"
        f"this_week={s['this_week_start']}..{s['this_week_end']}\n"
        f"this_month={s['this_month_start']}..{s['this_month_end']}\n"
        f"last_month={s['last_month_start']}..{s['last_month_end']}"
    )


def today_bounds(db=None, user=None) -> tuple[datetime, datetime, str]:
    now = now_local(db, user)
    start = datetime(now.year, now.month, now.day)
    return start, start + timedelta(days=1), start.date().isoformat()


def period_range(db, user, period: str) -> tuple[str, str]:
    key = (period or "").strip().lower()
    if key not in PERIODS:
        raise ValueError("period today|yesterday|this_week|this_month|last_month bo'lsin")
    s = snapshot(db, user)
    mapping = {
        "today": (s["today"], s["today"]),
        "yesterday": (s["yesterday"], s["yesterday"]),
        "this_week": (s["this_week_start"], s["this_week_end"]),
        "this_month": (s["this_month_start"], s["this_month_end"]),
        "last_month": (s["last_month_start"], s["last_month_end"]),
    }
    return mapping[key]
