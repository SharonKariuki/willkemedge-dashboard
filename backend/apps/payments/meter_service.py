"""
Water billing from meter readings.

Staff capture a meter reading for a unit; the system derives consumption from
the previous reading, prices it at the building's tariff, and bills it as a
``UtilityCharge`` — which posts to the GL (DR 1040 / CR 4150) and appears as
"Other Charges" on the tenant's statement.

Previously the only way a water charge could exist was the spreadsheet importer,
which carried the amount already computed in Excel. There was no tariff, no
calculator, and no staff-facing entry path.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from decimal import Decimal

from django.core.exceptions import ValidationError

WATER_LABEL = "Water Usage"


def previous_reading_for(tenant, *, label: str = WATER_LABEL, before: _dt.date | None = None) -> Decimal | None:
    """The closing reading of the tenant's most recent charge for this meter.

    This is what the staff form pre-fills as "previous reading", so the meter
    history stays continuous and nobody has to retype it.
    """
    from .models import UtilityCharge

    qs = UtilityCharge.objects.filter(tenant=tenant, label=label).exclude(closing_reading=None)
    if before:
        qs = qs.filter(posting_date__lt=before)
    last = qs.order_by("-posting_date", "-id").first()
    return last.closing_reading if last else None


def bill_meter_reading(
    *,
    tenant,
    period_month: int,
    period_year: int,
    closing_reading: Decimal,
    opening_reading: Decimal | None = None,
    label: str = WATER_LABEL,
    rate: Decimal | None = None,
) -> object:
    """Create (or update) the UtilityCharge for one meter reading.

    consumption = closing − opening   ·   amount = consumption × tariff

    Idempotent per (tenant, period, label), so re-submitting a corrected reading
    for the same month revises the charge instead of double-billing.
    """
    from .models import UtilityCharge

    closing = Decimal(str(closing_reading))

    if opening_reading is None:
        opening_reading = previous_reading_for(tenant, label=label)
    opening = Decimal(str(opening_reading)) if opening_reading is not None else None

    if opening is None:
        raise ValidationError(
            "No previous reading on file for this unit — enter the opening reading."
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

    try:
        posting_date = _dt.date(
            period_year, period_month, calendar.monthrange(period_year, period_month)[1]
        )
    except ValueError as exc:
        raise ValidationError(f"Invalid period {period_month}/{period_year}.") from exc

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
    return charge
