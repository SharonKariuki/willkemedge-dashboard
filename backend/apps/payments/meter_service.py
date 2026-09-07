"""
Water billing from meter readings.

Staff capture a meter reading for a unit; the system derives consumption from
the previous reading, prices it at the building's tariff, and bills it as a
``UtilityCharge`` — which posts to the GL (DR 1040 / CR 4150) and appears as
"Other Charges" on the tenant's statement.

Previously the only way a water charge could exist was the spreadsheet importer,
which carried the amount already computed in Excel. There was no tariff, no
calculator, and no staff-facing entry path.

The one invariant everything here defends: **a meter's history is a chain**.
Each month opens exactly where the previous month closed, so consumption is
partitioned across months with no gaps and no double-counting. Break the chain
anywhere and a tenant is billed for water nobody metered.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

WATER_LABEL = "Water Usage"


def _posting_date_for(period_year: int, period_month: int) -> _dt.date:
    """Charges post on the last day of the month they meter."""
    try:
        return _dt.date(
            period_year, period_month, calendar.monthrange(period_year, period_month)[1]
        )
    except ValueError as exc:
        raise ValidationError(f"Invalid period {period_month}/{period_year}.") from exc


def meter_history(tenant, *, label: str = WATER_LABEL):
    """Every charge on this unit's meter — tenant-agnostic — oldest period first.

    The meter is bolted to the unit, not to the person living behind it. When a
    tenant moves out the dial does not go back to zero, so the incoming tenant's
    first bill has to open where the outgoing tenant's last one closed. Scoping
    the history to the tenant would open the new tenant on a blank meter and
    hand them a first month of free water — or, if staff typed the real dial
    figure, a bill for the entire history of the unit.

    Ordered by period rather than ``posting_date`` because the period is what
    defines the chain; ``posting_date`` is derived from it, and a backfilled
    month must still sort into its own place in the sequence.
    """
    from .models import UtilityCharge

    qs = UtilityCharge.objects.filter(label=label)
    unit_id = getattr(tenant, "unit_id", None)
    qs = qs.filter(tenant__unit_id=unit_id) if unit_id else qs.filter(tenant=tenant)
    return qs.order_by("period_year", "period_month", "id")


def previous_reading_for(
    tenant,
    *,
    label: str = WATER_LABEL,
    before_period: tuple[int, int] | None = None,
) -> Decimal | None:
    """The closing reading on this meter immediately *before* ``before_period``.

    This is what the staff form pre-fills as "previous reading", so the meter
    history stays continuous and nobody has to retype it.

    The period matters. Reading off the newest charge regardless of period is
    right only while readings arrive in order; the moment staff backfill a
    missed month it hands them a *later* month's closing figure as that month's
    opening, which either bills negative consumption or trips the
    runs-backwards guard on a perfectly good reading.
    """
    qs = meter_history(tenant, label=label).exclude(closing_reading=None)
    if before_period:
        year, month = before_period
        qs = qs.filter(Q(period_year__lt=year) | Q(period_year=year, period_month__lt=month))
    last = qs.last()
    return last.closing_reading if last else None


def _rate_for(charge, fallback: Decimal | None) -> Decimal:
    """The tariff to re-price a charge at: its own first, the building's second.

    An existing charge is re-priced at the rate it was *actually billed* at,
    recovered from its stored amount and units, so re-deriving a month after the
    tariff moves from 150 to 200 does not quietly restate history. The statement
    is a record of what was charged, not a re-pricing of it.
    """
    rate = charge.rate_per_unit()
    if rate is None:
        rate = fallback
    return Decimal(str(rate)) if rate is not None else Decimal("0")


def recompute_chain_after(
    tenant,
    *,
    after_period: tuple[int, int],
    label: str = WATER_LABEL,
) -> list:
    """Re-derive every charge on this meter that follows ``after_period``.

    Correcting a reading is not a local edit. February opened where January
    closed, so revising January's closing figure leaves February — and every
    month after it — opening on a dial position that no longer exists. Left
    alone, that is a meter history with a hole in it and a tenant billed for
    consumption nobody metered.

    The walk stops at the first month it cannot chain through:

      * no closing reading — an imported row carrying only a value has no dial
        figure to hand forward, and inventing one would corrupt every month
        beyond it;
      * a closing below its opening — a meter swap or a rollover. That
        discontinuity is a fact about the hardware, not an error to smooth
        over, so the months after it keep the openings they were given.

    Returns the charges whose figures actually moved.
    """
    changed: list = []
    prior_closing: Decimal | None = None
    building = getattr(getattr(tenant, "unit", None), "building", None)
    building_rate = getattr(building, "water_rate_per_unit", None)

    for charge in meter_history(tenant, label=label):
        period = (charge.period_year, charge.period_month)
        if period <= after_period:
            if charge.closing_reading is not None:
                prior_closing = charge.closing_reading
            continue
        if charge.closing_reading is None:
            break
        # Nothing before it in the walk: this charge *is* the head of the chain,
        # so its own opening is the anchor — there is no earlier dial figure to
        # check it against, and refusing to start would leave a whole meter
        # unrepairable just because the correction began at its first month.
        opening = prior_closing if prior_closing is not None else charge.opening_reading
        closing = charge.closing_reading
        if opening is None or closing < opening:
            break

        rate = _rate_for(charge, building_rate)
        if rate <= 0:
            raise ValidationError(
                f"Cannot re-price {charge.label} {charge.period_month}/{charge.period_year} — "
                f"no tariff on the charge and none on the building. Set the building's "
                f"water rate, then save the reading again."
            )

        consumption = closing - opening
        amount = (consumption * rate).quantize(Decimal("0.01"))
        if (
            charge.opening_reading != opening
            or charge.units != consumption
            or charge.amount != amount
        ):
            charge.opening_reading = opening
            charge.units = consumption
            charge.amount = amount
            # post_save re-posts the journal entry, so the GL follows the
            # corrected figure instead of staying on the first one.
            charge.save(update_fields=["opening_reading", "units", "amount"])
            changed.append(charge)
        prior_closing = closing

    return changed


def bill_meter_reading(
    *,
    tenant,
    period_month: int,
    period_year: int,
    closing_reading: Decimal,
    opening_reading: Decimal | None = None,
    label: str = WATER_LABEL,
    rate: Decimal | None = None,
    meter_replaced: bool = False,
) -> object:
    """Create (or update) the UtilityCharge for one meter reading.

    consumption = closing − opening   ·   amount = consumption × tariff

    Idempotent per (tenant, period, label), so re-submitting a corrected reading
    for the same month revises the charge instead of double-billing — and the
    revision is carried forward through every later month on the same meter.
    """
    from .models import UtilityCharge

    period = (period_year, period_month)
    posting_date = _posting_date_for(period_year, period_month)
    closing = Decimal(str(closing_reading))

    carried = previous_reading_for(tenant, label=label, before_period=period)
    opening = Decimal(str(opening_reading)) if opening_reading is not None else carried

    if opening is None:
        raise ValidationError(
            "No previous reading on file for this unit — enter the opening reading."
        )
    if carried is not None and opening != carried and not meter_replaced:
        # A typed opening that disagrees with the figure the meter actually
        # closed on is either a typo or a meter swap. Both are worth stopping
        # for: accepting it silently bills a stretch of water twice, or not at
        # all, depending on which way the mismatch runs.
        raise ValidationError(
            f"Opening reading ({opening}) does not match the closing reading already on "
            f"file for this meter ({carried}). Correct the figure, or confirm the meter "
            f"was replaced if the dial restarted."
        )
    if closing < opening:
        raise ValidationError(
            f"Closing reading ({closing}) is below the previous reading ({opening}). "
            f"A meter cannot run backwards — check the figure."
        )

    if rate is None:
        rate = getattr(tenant.unit.building, "water_rate_per_unit", None) or Decimal("0")
    rate = Decimal(str(rate))
    if rate <= 0:
        raise ValidationError(
            "This building has no water tariff set — cannot price the consumption."
        )

    consumption = closing - opening
    amount = (consumption * rate).quantize(Decimal("0.01"))

    with transaction.atomic():
        charge, _created = UtilityCharge.objects.update_or_create(
            tenant=tenant, period_month=period_month, period_year=period_year, label=label,
            defaults={
                "posting_date": posting_date,
                "opening_reading": opening,
                "closing_reading": closing,
                "units": consumption,
                "amount": amount,
            },
        )
        recompute_chain_after(tenant, after_period=period, label=label)
    return charge
