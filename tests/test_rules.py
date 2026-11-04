from datetime import date, datetime

import pytest

from emporio_agent.config import STORE_TZ
from emporio_agent.rules import evaluate_return, holidays, store_status


def at(*args):
    return datetime(*args, tzinfo=STORE_TZ)


@pytest.mark.parametrize(
    "now, is_open",
    [
        (at(2026, 3, 25, 10, 0), True),    # Wednesday
        (at(2026, 3, 25, 8, 59), False),
        (at(2026, 3, 25, 18, 0), False),   # closes at 18:00
        (at(2026, 3, 28, 12, 59), True),   # Saturday until 13:00
        (at(2026, 3, 28, 13, 0), False),
        (at(2026, 3, 29, 10, 0), False),   # Sunday
        (at(2026, 4, 3, 10, 0), False),    # Good Friday 2026
        (at(2026, 4, 21, 10, 0), False),   # Tiradentes (Tuesday)
    ],
)
def test_store_hours(now, is_open):
    assert store_status(now)["is_open"] is is_open


def test_next_opening_skips_weekend_and_holidays():
    assert store_status(at(2026, 3, 28, 14, 0))["next_opening"] == at(2026, 3, 30, 9, 0)
    assert store_status(at(2026, 4, 2, 18, 30))["next_opening"] == at(2026, 4, 4, 9, 0)  # skips Good Friday
    assert store_status(at(2026, 3, 25, 7, 0))["next_opening"] == at(2026, 3, 25, 9, 0)


def test_holiday_calendar():
    h = holidays(2026)
    assert h[date(2026, 4, 3)] == "Sexta-feira Santa"
    assert date(2026, 10, 11) in h and date(2026, 8, 26) in h


def test_regret_window_is_seven_days_from_receipt_inclusive():
    received = date(2026, 3, 20)
    on_deadline = evaluate_return("arrependimento", date(2026, 3, 10), received, date(2026, 3, 27))
    assert on_deadline["eligible"] is True and on_deadline["deadline"] == date(2026, 3, 27)
    late = evaluate_return("arrependimento", date(2026, 3, 10), received, date(2026, 3, 28))
    assert late["eligible"] is False and late["days_elapsed"] == 8


def test_defect_window_counts_from_purchase():
    r = evaluate_return("defeito", date(2026, 3, 1), date(2026, 3, 20), date(2026, 3, 31))
    assert r["eligible"] is True and r["deadline"] == date(2026, 3, 31)
    r = evaluate_return("defeito", date(2026, 3, 1), date(2026, 3, 20), date(2026, 4, 1))
    assert r["eligible"] is False


def test_regret_not_started_before_receipt_and_legal_warranty():
    r = evaluate_return("arrependimento", date(2026, 3, 1), None, date(2026, 3, 5))
    assert r["eligible"] is None
    r = evaluate_return("preferencia", date(2026, 1, 1), date(2026, 1, 10), date(2026, 3, 1))
    assert r["eligible"] is False
    assert r["legal_warranty"] == {"active": True, "until": date(2026, 4, 10)}
