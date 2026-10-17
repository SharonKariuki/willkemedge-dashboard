"""
Charges added by hand — the owner's Add Charge screen.

A charge is a debit on the tenant's account that is not rent: a late penalty,
parking, a damage/repair recharge, or a flat utility bill. It is stored as a
``UtilityCharge`` so it lands in "Other Charges" on the statement and the rent
roll exactly like water does; ``charge_type`` decides the account it is booked
to (``apps.ledger.posting.charge_account_code``).

Like credits, posting is STRICT here: the ``post_save`` signal posts the entry,
and if it could not, the whole action rolls back. A charge on the tenant's
account that is not in the books is the drift the ledger exists to stop.

Mistakes are corrected the way any charge is — Add Credit → "We charged too
much" against this charge — which unwinds the same account it was booked to.
"""
from __future__ import annotations

import datetime as _dt
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.accounts import audit

from .models import ChargeType, UtilityCharge

CENTS = Decimal("0.01")

#: Tenants a charge may still be raised against. A moved-out tenant can owe a
#: damage recharge found at handover; an archived record is closed.
CHARGEABLE_STATUSES = ("active", "notice_given", "moved_out")

#: Two identical charges inside this window are a double submit, not two bills.
DUPLICATE_WINDOW = timedelta(minutes=2)


class ChargeError(Exception):
    """A charge that cannot be added as asked. The message is for the owner."""


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(CENTS)
    except (InvalidOperation, TypeError, ValueError):
        raise ChargeError("Enter the amount as a number, e.g. 2500.") from None


def _next_period(today: _dt.date) -> tuple[int, int]:
    return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)


def _validate(tenant, charge_type, *, amount, label, posting_date, period_month, period_year,
              expense_category, today):
    if tenant.status not in CHARGEABLE_STATUSES:
        raise ChargeError("This tenant's record is archived; it cannot take new charges.")
    if charge_type not in ChargeType.values:
        raise ChargeError("Choose what the charge is for.")
    if amount <= 0:
        raise ChargeError("Enter an amount greater than 0. To give money back, add a credit instead.")
    if not label.strip():
        raise ChargeError("Enter the description the tenant will see on their statement.")
    if posting_date > today:
        raise ChargeError("The charge date cannot be in the future.")
    if not 1 <= period_month <= 12:
        raise ChargeError("Choose the month the charge belongs to.")
    if (period_year, period_month) > _next_period(today):
        # Next month is allowed: statements go out on the 25th/28th for it.
        raise ChargeError("A charge can be for next month at the latest.")

    if charge_type == ChargeType.DAMAGE:
        if expense_category is None or not expense_category.account_id:
            raise ChargeError("Choose which expense this recharge recovers, e.g. Repairs & Maintenance.")
        from apps.expenses.models import AccountType

        if expense_category.account.account_type != AccountType.EXPENSE:
            raise ChargeError("A recharge must recover an expense account.")
    elif expense_category is not None:
        raise ChargeError("An expense category only applies to a damage or repair recharge.")

    if label.casefold() in _metered_labels(tenant):
        # Meter bills are found again by (tenant, month, label). A hand-made
        # charge under the same label would be overwritten by the next reading,
        # or make it fail outright, and would break the unit's meter chain.
        raise ChargeError(
            f"'{label}' is billed from meter readings. Enter it on the Water Readings "
            f"page, or give this charge a different description."
        )


def _metered_labels(tenant) -> set[str]:
    from .meter_service import WATER_LABEL

    labels = {WATER_LABEL.casefold()}
    unit_id = getattr(tenant, "unit_id", None)
    readings = UtilityCharge.objects.exclude(closing_reading=None)
    readings = readings.filter(tenant__unit_id=unit_id) if unit_id else readings.filter(tenant=tenant)
    labels.update(label.casefold() for label in readings.values_list("label", flat=True).distinct())
    return labels


@transaction.atomic
def add_charge(
    *,
    tenant,
    charge_type: str,
    amount,
    label: str,
    posting_date: _dt.date,
    period_month: int,
    period_year: int,
    actor=None,
    expense_category=None,
    notes: str = "",
    today: _dt.date | None = None,
) -> UtilityCharge:
    """Add a debit to a tenant's account: save it, book it, audit it."""
    from apps.ledger.models import JournalEntry
    from apps.tenants.models import Tenant

    today = today or timezone.localdate()
    amount = _money(amount)
    label = (label or "").strip()[:60]
    _validate(
        tenant, charge_type, amount=amount, label=label, posting_date=posting_date,
        period_month=period_month, period_year=period_year,
        expense_category=expense_category, today=today,
    )

    # Lock the tenant so two clicks are seen one after the other.
    Tenant.objects.select_for_update().filter(pk=tenant.pk).first()
    if UtilityCharge.objects.filter(
        tenant=tenant, charge_type=charge_type, label=label, amount=amount,
        period_month=period_month, period_year=period_year,
        created_at__gte=timezone.now() - DUPLICATE_WINDOW,
    ).exists():
        raise ChargeError("This exact charge was just added. Check the tenant's statement before adding it again.")

    user = actor if getattr(actor, "is_authenticated", False) else None
    charge = UtilityCharge.objects.create(
        tenant=tenant,
        charge_type=charge_type,
        expense_category=expense_category,
        label=label,
        amount=amount,
        posting_date=posting_date,
        period_month=period_month,
        period_year=period_year,
        notes=notes or "",
        created_by=user,
    )

    # The post_save signal books it best-effort; a manual charge must be booked.
    if not JournalEntry.objects.filter(
        source_type="utility_charge", source_id=charge.pk, kind="normal",
    ).exists():
        raise ChargeError("The charge could not be booked to the accounts, so it was not added. Try again.")

    audit.record(
        actor=actor,
        action="charge.add",
        object_type="utility_charge",
        object_id=charge.pk,
        summary=(
            f"Charge of KES {charge.amount} to {tenant} — "
            f"{charge.get_charge_type_display()}: {charge.label}"
        ),
        new_values={
            "tenant_id": tenant.pk,
            "charge_type": charge.charge_type,
            "label": charge.label,
            "amount": charge.amount,
            "posting_date": charge.posting_date,
            "period": f"{charge.period_month}/{charge.period_year}",
            "expense_category_id": charge.expense_category_id,
            "notes": charge.notes,
        },
    )
    return charge
