"""Money rounding — tax-inclusive QQS, 2 decimal places, ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")
CASHIER_MAX_DISCOUNT_PCT = 10


def as_dec(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def money2(value) -> float:
    return float(as_dec(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def vat_included(total, vat_percent) -> float:
    """QQS included in price: tax = total * vat / (100 + vat)."""
    vat = as_dec(vat_percent)
    tot = as_dec(total)
    if vat <= 0 or tot <= 0:
        return 0.0
    return money2(tot * vat / (Decimal(100) + vat))
