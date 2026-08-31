"""Which month the books are billing on a given day.

Tenants asked to be told what they owe *before* the month starts rather than
after it has already begun, so the cycle runs a month ahead of the calendar:
from ``STATEMENT_RUN_DAY`` (the 25th) onwards the system raises the following
month's rent and states it. 25 August 2026 bills and states September 2026.

Everything that has to agree on "which month are we billing?" reads
:func:`billing_period` — the arrears run that raises the charge, the statement
run that emails it, and the manual re-send the office makes from the dashboard.
Working it out separately in each place is how the statement and the ledger end
up disagreeing about what a tenant owes.

Two things follow from billing a month before it starts, and both are load-
bearing elsewhere:

  * A September ``Arrears`` row exists from 25 August, but September rent is
    not *overdue* in August. Everything that reports debt already filters to
    periods at or before the current month (``monthly_ledger.upto_current_period``,
    ``aging``, ``buildings.services``); anything new that sums ``Arrears`` must
    do the same or it will report the whole roster a month in arrears for the
    last week of every month.
  * The external scheduler (``.github/workflows/scheduled-jobs.yml``) has to
    fire ``monthly-arrears`` and ``monthly-statements`` on the day this names.
    Move one without the other and the run either states a month it has not
    raised, or raises next month and states this one.
"""
from __future__ import annotations

import calendar
import datetime as _dt

from django.utils import timezone

# The 25th: late enough that the closing month is essentially settled, early
# enough to give tenants a week before rent falls due on the 5th.
DEFAULT_STATEMENT_RUN_DAY = 25


def statement_run_day() -> int:
    """The day of the month the billing cycle rolls forward on.

    Clamped to 1..28 so it lands in every month, February included — a run day
    of 31 would silently never fire in half the year.
    """
    from django.conf import settings

    try:
        day = int(getattr(settings, "STATEMENT_RUN_DAY", DEFAULT_STATEMENT_RUN_DAY))
    except (TypeError, ValueError):
        return DEFAULT_STATEMENT_RUN_DAY
    return max(1, min(day, 28))


def next_period(year: int, month: int) -> tuple[int, int]:
    """The ``(year, month)`` after this one."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


def billing_period(today: _dt.date | None = None) -> tuple[int, int]:
    """The ``(year, month)`` the books are billing on ``today``.

    Next month from the run day onwards, this month before it. A statement run
    on 25 August 2026 therefore returns ``(2026, 9)``.
    """
    today = today or timezone.localdate()
    if today.day >= statement_run_day():
        return next_period(today.year, today.month)
    return (today.year, today.month)


def period_start(period: tuple[int, int]) -> _dt.date:
    """The first day of ``period`` — the date its rent is posted on."""
    return _dt.date(period[0], period[1], 1)


def period_end(period: tuple[int, int]) -> _dt.date:
    """The last day of ``period``."""
    year, month = period
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def parse_period(period_iso: str) -> tuple[int, int]:
    """``"2026-09"`` -> ``(2026, 9)``. Raises ValueError on anything else."""
    year, _, month = period_iso.partition("-")
    period = (int(year), int(month))
    if not 1 <= period[1] <= 12:
        raise ValueError(f"month out of range: {period_iso!r}")
    return period
