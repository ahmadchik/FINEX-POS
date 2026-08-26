from datetime import datetime, timedelta

PLANS = {
    "FREE": {
        "price": 0,
        "stores": 1,
        "users": 2,
        "trial_days": 30,
        "label": "FREE",
    },
    "PRO": {
        "price": 80_000,
        "stores": 1,
        "users": 3,
        "trial_days": 0,
        "label": "PRO",
    },
    "ENTERPRISE": {
        "price": 160_000,
        "stores": 5,
        "users": 999,
        "trial_days": 0,
        "label": "ENTERPRISE",
    },
    "VIP": {
        "price": 500_000,
        "stores": 9999,
        "users": 9999,
        "trial_days": 0,
        "label": "VIP",
    },
}


def plan_of(code: str) -> dict:
    return PLANS.get((code or "FREE").upper(), PLANS["FREE"])


def refresh_company_status(company) -> str:
    if not company:
        return "SUSPENDED"
    if (company.status or "").upper() == "SUSPENDED":
        return "SUSPENDED"
    now = datetime.utcnow()
    paid = company.paid_until
    trial = company.trial_ends_at
    if paid and paid >= now:
        company.status = "ACTIVE"
        return "ACTIVE"
    if (company.plan or "FREE").upper() == "FREE" and trial and trial >= now:
        company.status = "TRIAL"
        return "TRIAL"
    company.status = "PAST_DUE"
    return "PAST_DUE"


def is_writable(company) -> bool:
    return refresh_company_status(company) in ("ACTIVE", "TRIAL")
