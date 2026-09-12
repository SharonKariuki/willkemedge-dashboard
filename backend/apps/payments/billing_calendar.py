"""Which month the books are billing for a given letting on a given day.

Rent falls due on the 5th of the month it covers, for everybody. What differs
is when the charge is *raised*, and there are two cycles:

  * **Residential** — raised on the 1st, for the month that has just started.
    A tenant in a house or a bedsitter is billed for September on 1 September
    and pays by 5 September. This is the landlord's standing instruction and
    the cycle the great majority of the roster is on.
  * **Commercial** — raised on ``STATEMENT_RUN_DAY`` (the 25th), for the month
    *ahead*. The arcade's VAT invoice has to be in the tenant's hands before
    the month it covers begins, so 25 August raises and states September.

``UnitClassification.BUSINESS`` is the axis, the same one the VAT rate, the
deposit rule and the statement layout already turn on — so a future commercial
letting lands on the advance cycle without anyone remembering to add it here.

Everything that has to agree on "which month are we billing for this tenant?"
reads :func:`tenant_billing_period`: the arrears run that raises the charge,
the statement run that emails it, and the manual re-send the office makes from
the dashboard. Working it out separately in each place is how the statement and
the ledger end up disagreeing about what a tenant owes.

Two things follow from the commercial cycle billing a month before it starts,
and both are load-bearing elsewhere:

  * A September ``Arrears`` row exists from 25 August, but September rent is
    not *overdue* in August. Everything that reports debt already filters to
    periods at or before the current month (``monthly_ledger.upto_current_period``,
    ``aging``, ``buildings.services``); anything new that sums ``Arrears`` must
    do the same or it will report the arcade a month in arrears for the last
    week of every month.
  * The external scheduler (``.github/workflows/scheduled-jobs.yml``) has to
    fire ``monthly-arrears`` and ``monthly-statements`` on BOTH days this
    module names — the 1st for residential and the 25th for commercial. Drop
    one day and that half of the roster is never billed; move a day without
    moving ``STATEMENT_RUN_DAY`` and the run states a month it has not raised.

The residential cycle needs no run day of its own: ``billing_period`` returns
the current calendar month on every day before the 25th, so the 1st-of-month
run raises exactly the month that has just begun.
"""
from __future__ import annotations

import calendar
import datetime as _dt

from django.utils import timezone

# The 25th: late enough that the closing month is essentially settled, early
# enough to give a commercial tenant a week before rent falls due on the 5th.
DEFAULT_STATEMENT_RUN_DAY = 25

#: The day rent falls due, in the month it covers. Residential rent is raised
#: on the 1st and commercial on the 25th before, but both are payable by this
#: day of the month being billed — which is why it is one constant and not a
#: property of either cycle. ``Tenant.due_day`` defaults to it.
RENT_DUE_DAY = 5


def statement_run_day() -> int:
    """The day of the month the COMMERCIAL cycle rolls forward on.

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


def bills_in_advance(tenant) -> bool:
    """Whether this letting is invoiced before the month it covers.

    True for a commercial letting, which is invoiced on the 25th for the month
    ahead. A tenancy with no unit has no classification to read and falls to
    the residential cycle, which is the portfolio default.
    """
    from apps.buildings.models import UnitClassification

    unit = getattr(tenant, "unit", None)
    return unit is not None and unit.classification == UnitClassification.BUSINESS


def billing_period(today: _dt.date | None = None, *, advance: bool = True) -> tuple[int, int]:
    """The ``(year, month)`` the books are billing on ``today``.

    With ``advance`` (the commercial cycle) it is next month from the run day
    onwards and this month before it, so a run on 25 August 2026 returns
    ``(2026, 9)``. Without it (the residential cycle) it is always the current
    calendar month, so the 1st-of-month run raises the month just begun.

    Prefer :func:`tenant_billing_period`, which picks ``advance`` from the
    letting rather than making each caller remember which cycle it is on.
    """
    today = today or timezone.localdate()
    if advance and today.day >= statement_run_day():
        return next_period(today.year, today.month)
    return (today.year, today.month)


def tenant_billing_period(tenant, today: _dt.date | None = None) -> tuple[int, int]:
    """The ``(year, month)`` this tenant is being billed for on ``today``.

    The one function to ask. On 25 August 2026 an arcade tenant is on September
    and a residential tenant is still on August — the month they were billed
    for on the 1st and have already been sent a statement for.
    """
    return billing_period(today, advance=bills_in_advance(tenant))


def period_start(period: tuple[int, int]) -> _dt.date:
    """The first day of ``period`` — the date its rent is posted on."""
    return _dt.date(period[0], period[1], 1)


def period_end(period: tuple[int, int]) -> _dt.date:
    """The last day of ``period``."""
    year, month = period
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def rent_due_date(period: tuple[int, int], due_day: int | None = None) -> _dt.date:
    """The date rent for ``period`` falls due — the 5th of that month.

    ``due_day`` overrides it for a letting agreed on another day; it is clamped
    to the month's length so February cannot raise ValueError.
    """
    year, month = period
    day = int(due_day) if due_day else RENT_DUE_DAY
    return _dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def parse_period(period_iso: str) -> tuple[int, int]:
    """``"2026-09"`` -> ``(2026, 9)``. Raises ValueError on anything else."""
    year, _, month = period_iso.partition("-")
    period = (int(year), int(month))
    if not 1 <= period[1] <= 12:
        raise ValueError(f"month out of range: {period_iso!r}")
    return period
