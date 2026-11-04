from decimal import Decimal

import pytest

from emporio_agent import pricing


def test_brl_format():
    assert pricing.fmt_brl(2199) == "R$ 2.199,00"
    assert pricing.fmt_brl(11499) == "R$ 11.499,00"
    assert pricing.fmt_brl(85.98) == "R$ 85,98"
    assert pricing.fmt_brl(0) == "R$ 0,00"


def test_promotional_price():
    assert pricing.promotional_price(2399, 18) == Decimal("1967.18")
    assert pricing.promotional_price(5999, 8) == Decimal("5519.08")
    assert pricing.promotional_price(2199, None) == Decimal("2199.00")


def test_pix_discount_only_without_promotion():
    assert pricing.pix_price(2199, has_active_promotion=False) == Decimal("2089.05")
    assert pricing.pix_price(2399, has_active_promotion=True) is None


@pytest.mark.parametrize(
    "amount, expected",
    [
        (49.90, 1),     # below R$ 50: no installments
        (50.00, 3),     # up to 3x, no minimum installment
        (159.90, 3),    # 4x would be R$ 39,98 < R$ 80
        (429.90, 5),    # 5x = R$ 85,98; 6x = R$ 71,65 < R$ 80
        (599.90, 6),    # 6x = R$ 99,98 >= R$ 80; 7x = R$ 85,70 < R$ 100
        (1199.00, 11),  # 11x = R$ 109,00; 12x = R$ 99,92 < R$ 100
        (1200.00, 12),  # 12x = R$ 100,00 exactly
        (2199.00, 12),
    ],
)
def test_max_installments_follow_section_3_1(amount, expected):
    assert pricing.max_installments(amount) == expected


def test_installment_values():
    assert pricing.installment_value(2199, 10) == Decimal("219.90")
    options = pricing.installment_options(429.90)
    assert [n for n, _ in options] == [1, 2, 3, 4, 5]
    assert options[-1][1] == Decimal("85.98")


def test_combined_payment_only_above_2000():
    assert not pricing.combined_payment_allowed(2000)
    assert pricing.combined_payment_allowed(2000.01)


def test_metro_shipping():
    assert pricing.metro_shipping_fee(499.99) == Decimal("35.00")
    assert pricing.metro_shipping_fee(500.00) == Decimal("35.00")  # "acima de R$ 500" is strict
    assert pricing.metro_shipping_fee(500.01) == Decimal("0.00")
    assert pricing.is_metro_city("Campo Grande")
    assert pricing.is_metro_city(" campo grande ")
    assert not pricing.is_metro_city("Dourados")
    assert not pricing.is_metro_city(None)
