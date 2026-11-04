"""Money rules from the policy manual, as pure functions (sections 3, 3.1, 5.1 and 6.2).

All arithmetic uses Decimal and rounds half-up to the cent. The language model never
computes any of these numbers; it only reads what the tools return.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .db import strip_accents

CENT = Decimal("0.01")
PIX_DISCOUNT_RATE = Decimal("0.05")                 # 3: 5% off the list price
MIN_PURCHASE_FOR_INSTALLMENTS = Decimal("50.00")    # 3.1: "sem valor mínimo (exceto abaixo de R$ 50)"
INSTALLMENT_BANDS = [                               # 3.1: (from n, to n, minimum installment)
    (1, 3, Decimal("0")),
    (4, 6, Decimal("80.00")),
    (7, 12, Decimal("100.00")),
]
MAX_INSTALLMENTS = 12
COMBINED_PAYMENT_ABOVE = Decimal("2000.00")         # 3.1: PIX + card only above R$ 2.000
METRO_FREE_SHIPPING_ABOVE = Decimal("500.00")       # 5.1
METRO_SHIPPING_FEE = Decimal("35.00")               # 5.1
METRO_CITIES = {"campo grande"}                     # see README, Assumptions


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_brl(value) -> str:
    """Brazilian currency format: 2199 -> 'R$ 2.199,00'."""
    q = money(value)
    integer, cents = f"{q:.2f}".split(".")
    sign = "-" if integer.startswith("-") else ""
    integer = integer.lstrip("-")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}R$ {'.'.join(groups)},{cents}"


def promotional_price(list_price, discount_percent) -> Decimal:
    """List price with an active promotion applied (6.2)."""
    if not discount_percent:
        return money(list_price)
    factor = (Decimal("100") - Decimal(str(discount_percent))) / Decimal("100")
    return money(Decimal(str(list_price)) * factor)


def pix_price(list_price, has_active_promotion: bool) -> Decimal | None:
    """5% off the list price, only when there is no promotion: discounts do not stack (6.2)."""
    if has_active_promotion:
        return None
    return money(Decimal(str(list_price)) * (1 - PIX_DISCOUNT_RATE))


def installments_allowed(amount, n: int) -> bool:
    """Whether ``amount`` can be split into ``n`` interest-free installments (3.1)."""
    amount = Decimal(str(amount))
    if n < 1 or n > MAX_INSTALLMENTS:
        return False
    if n == 1:
        return True
    if amount < MIN_PURCHASE_FOR_INSTALLMENTS:
        return False
    for low, high, minimum in INSTALLMENT_BANDS:
        if low <= n <= high:
            return amount / n >= minimum
    return False


def max_installments(amount) -> int:
    return max(n for n in range(1, MAX_INSTALLMENTS + 1) if installments_allowed(amount, n))


def installment_value(amount, n: int) -> Decimal:
    return money(Decimal(str(amount)) / n)


def installment_options(amount) -> list[tuple[int, Decimal]]:
    return [(n, installment_value(amount, n)) for n in range(1, max_installments(amount) + 1)]


def combined_payment_allowed(amount) -> bool:
    return Decimal(str(amount)) > COMBINED_PAYMENT_ABOVE


def is_metro_city(city: str | None) -> bool:
    return strip_accents((city or "").strip().lower()) in METRO_CITIES


def metro_shipping_fee(order_value) -> Decimal:
    """5.1: free above R$ 500,00; otherwise a flat R$ 35,00."""
    return Decimal("0.00") if Decimal(str(order_value)) > METRO_FREE_SHIPPING_ABOVE else METRO_SHIPPING_FEE
