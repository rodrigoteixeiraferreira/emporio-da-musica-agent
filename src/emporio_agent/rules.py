"""Date rules from the policy manual, as pure functions: opening hours (2), return and
exchange windows (4.1-4.3) and the legal warranty (8.1)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

# 2. Monday=0 ... Sunday=6. None = closed.
WEEKLY_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9), time(18)),
    1: (time(9), time(18)),
    2: (time(9), time(18)),
    3: (time(9), time(18)),
    4: (time(9), time(18)),
    5: (time(9), time(13)),
    6: None,
}
WEEKDAYS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

# 4.1-4.3: (days, counted from). "receipt" for regret and preference, "purchase" for defects.
RETURN_WINDOWS = {
    "arrependimento": (7, "receipt"),
    "preferencia": (7, "receipt"),
    "defeito": (30, "purchase"),
}
LEGAL_WARRANTY_DAYS = 90  # 8.1, counted from receipt


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays(year: int) -> dict[date, str]:
    """National holidays, the Mato Grosso do Sul state holiday and Campo Grande's anniversary.

    Carnival and Corpus Christi are optional days nationally and are treated as regular days.
    """
    fixed = {
        (1, 1): "Confraternização Universal",
        (4, 21): "Tiradentes",
        (5, 1): "Dia do Trabalho",
        (8, 26): "Aniversário de Campo Grande",
        (9, 7): "Independência do Brasil",
        (10, 11): "Criação do Estado de Mato Grosso do Sul",
        (10, 12): "Nossa Senhora Aparecida",
        (11, 2): "Finados",
        (11, 15): "Proclamação da República",
        (11, 20): "Dia da Consciência Negra",
        (12, 25): "Natal",
    }
    result = {date(year, m, d): name for (m, d), name in fixed.items()}
    result[_easter(year) - timedelta(days=2)] = "Sexta-feira Santa"
    return result


def hours_on(day: date) -> tuple[time, time] | None:
    if day in holidays(day.year):
        return None
    return WEEKLY_HOURS[day.weekday()]


def store_status(now: datetime) -> dict:
    """Whether the store (and the human WhatsApp team) is open at ``now`` (store time zone)."""
    today = now.date()
    hours = hours_on(today)
    holiday = holidays(today.year).get(today)
    is_open = bool(hours and hours[0] <= now.time() < hours[1])

    next_open = None
    if not is_open:
        for offset in range(0, 15):
            day = today + timedelta(days=offset)
            h = hours_on(day)
            if h and (offset > 0 or now.time() < h[0]):
                next_open = datetime.combine(day, h[0], tzinfo=now.tzinfo)
                break

    return {
        "is_open": is_open,
        "today_hours": f"{hours[0]:%H:%M} às {hours[1]:%H:%M}" if hours else "fechado",
        "holiday": holiday,
        "closes_at": f"{hours[1]:%H:%M}" if is_open else None,
        "next_opening": next_open,
    }


def evaluate_return(reason: str, order_date: date, received_on: date | None, today: date) -> dict:
    """Apply the window for ``reason`` and report the legal warranty (8.1) as a fallback.

    ``eligible`` is None when the window starts at receipt and the order was not received yet.
    """
    days, counted_from = RETURN_WINDOWS[reason]
    start = order_date if counted_from == "purchase" else received_on
    result: dict = {"reason": reason, "window_days": days, "counted_from": counted_from}

    if start is None:
        result.update(eligible=None, start_date=None, deadline=None, days_elapsed=None, days_left=None)
    else:
        deadline = start + timedelta(days=days)
        elapsed = (today - start).days
        result.update(
            eligible=today <= deadline,
            start_date=start,
            deadline=deadline,
            days_elapsed=elapsed,
            days_left=max((deadline - today).days, 0),
        )

    if received_on is None:
        result["legal_warranty"] = {"active": None, "until": None}
    else:
        until = received_on + timedelta(days=LEGAL_WARRANTY_DAYS)
        result["legal_warranty"] = {"active": today <= until, "until": until}
    return result
