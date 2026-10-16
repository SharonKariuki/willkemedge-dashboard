"""Which month the books are billing for a given letting on a given day.

Every letting is invoiced a month AHEAD, and rent falls due on the 5th of the
month it covers. The two kinds of letting differ only in the day the invoice
is generated and sent:

  * **Residential** — on ``RESIDENTIAL_RUN_DAY`` (the 28th). October's rent is
    invoiced on 28 September, together with September's water.
  * **Commercial** — on ``STATEMENT_RUN_DAY`` (the 25th). October's rent is
    invoiced on 25 September, together with September's water. The arcade's
    VAT invoice has to be in the tenant's hands before the month it covers.

So one invoice carries two different months, and they must not be confused:

  * the **rent period** — the month after the one the invoice is sent in;
  * the **water period** — the month the invoice is sent in, metered up to
    that day. :func:`usage_invoice_period` maps one to the other.

``UnitClassification.BUSINESS`` is the axis, the same one the VAT rate, the
deposit rule and the statement layout already turn on — so a future commercial
letting lands on the right day without anyone remembering to add it here.

Everything that has to agree on "which month are we billing for this tenant?"
reads :func:`tenant_billing_period`: the arrears run that raises the charge,
the statement run that emails it, and the manual re-send the office makes from
the dashboard. Working it out separately in each place is how the statement and
the ledger end up disagreeing about what a tenant owes.

Two things follow from billing a month before it starts, and both are
load-bearing elsewhere:

  * An October ``Arrears`` row exists from 25 or 28 September, but October rent
    is not *overdue* in September. Everything that reports debt already filters
    to periods at or before the current month (``monthly_ledger.upto_current_period``,
    ``aging``, ``buildings.services``); anything new that sums ``Arrears`` must
    do the same or it will report the whole roster a month in arrears for the
    last days of every month.
  * The external scheduler (``.github/workflows/scheduled-jobs.yml``) has to
    fire ``monthly-arrears`` and ``monthly-statements`` on BOTH run days — the
    25th and the 28th. Drop one and that half of the roster is never invoiced
    on time; move a day without moving its setting and the run states a month
    it has not raised. The 1st is kept as a catch-up for both.
"""
from __future__ import annotations

import calendar
import datetime as _dt

from django.utils import timezone

# The 25th: late enough that the closing month is essentially settled, early
# enough to give a commercial tenant over a week before rent falls due.
DEFAULT_COMMERCIAL_RUN_DAY = 25

# The 28th: the latest day that exists in every month, February included, so
# a residential tenant's water is metered as far into the month as possible.
DEFAULT_RESIDENTIAL_RUN_DAY = 28

#: The day rent falls due, in the month it covers. Both kinds of letting are
#: invoiced in the month before, on different days, but both are payable by
#: this day of the month being billed — which is why it is one constant and not
#: a property of either. ``Tenant.due_day`` defaults to it.
RENT_DUE_DAY = 5


def _run_day_setting(name: str, default: int) -> int:
    """A run day from settings, clamped to 1..28 so it lands in every month.

    A run day of 31 would silently never fire in half the year.
    """
    from django.conf import settings

    try:
        day = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(1, min(day, 28))


def commercial_run_day() -> int:
    """The day of the month commercial lettings are invoiced for the next."""
    return _run_day_setting("STATEMENT_RUN_DAY", DEFAULT_COMMERCIAL_RUN_DAY)


def residential_run_day() -> int:
    """The day of the month residential lettings are invoiced for the next."""
    return _run_day_setting("RESIDENTIAL_RUN_DAY", DEFAULT_RESIDENTIAL_RUN_DAY)


def next_period(year: int, month: int) -> tuple[int, int]:
    """The ``(year, month)`` after this one."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


def previous_period(year: int, month: int) -> tuple[int, int]:
    """The ``(year, month)`` before this one."""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def is_commercial(tenant) -> bool:
    """Whether this letting is on the commercial (25th) invoice day.

    A tenancy with no unit has no classification to read and falls to the
    residential day, which is the portfolio default.
    """
    from apps.buildings.models import UnitClassification

    unit = getattr(tenant, "unit", None)
    return unit is not None and unit.classification == UnitClassification.BUSINESS


def run_day_for(tenant) -> int:
    """The day of the month this letting is invoiced on."""
    return commercial_run_day() if is_commercial(tenant) else residential_run_day()


def billing_period(today: _dt.date | None = None, *, run_day: int | None = None) -> tuple[int, int]:
    """The ``(year, month)`` the books are billing on ``today``.

    Next month from ``run_day`` onwards, this month before it: with the
    commercial run day (the default) 25 August 2026 returns ``(2026, 9)`` and
    24 August returns ``(2026, 8)``.

    Prefer :func:`tenant_billing_period`, which picks the run day from the
    letting rather than making each caller remember which day it is on.
    """
    today = today or timezone.localdate()
    day = commercial_run_day() if run_day is None else run_day
    if today.day >= day:
        return next_period(today.year, today.month)
    return (today.year, today.month)


def tenant_billing_period(tenant, today: _dt.date | None = None) -> tuple[int, int]:
    """The ``(year, month)`` this tenant is being billed for on ``today``.

    The one function to ask. On 26 September 2026 an arcade tenant is on
    October and a residential tenant is still on September, until the 28th.
    """
    return billing_period(today, run_day=run_day_for(tenant))


def invoice_date(tenant, period: tuple[int, int]) -> _dt.date:
    """The day ``period``'s rent is invoiced on — its run day, a month early.

    October 2026 is invoiced on 28 September for a house and on 25 September
    for a shop. Takes no account of move-in; callers that print it do.
    """
    year, month = previous_period(*period)
    return _dt.date(year, month, run_day_for(tenant))


def usage_invoice_period(year: int, month: int) -> tuple[int, int]:
    """The rent period whose invoice carries metered usage for ``(year, month)``.

    September's water is read up to the September run day and billed on the
    invoice sent that day — the one for October's rent.
    """
    return next_period(year, month)


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
