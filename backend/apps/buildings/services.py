"""
Unit status transition service.

All status changes go through this module so business rules are enforced
in one place. The payment system (Day 4) will call recalculate_unit_status()
after processing each payment.

Allowed transitions:
    VACANT          → OCCUPIED_UNPAID   (tenant moves in)
    OCCUPIED_*      → VACANT            (tenant moves out)
    OCCUPIED_UNPAID → OCCUPIED_PARTIAL  (partial payment received)
    OCCUPIED_UNPAID → OCCUPIED_PAID     (full payment received)
    OCCUPIED_PARTIAL→ OCCUPIED_PAID     (remaining balance paid)
    OCCUPIED_PAID   → OCCUPIED_UNPAID   (new month rolls over, no payment yet)
    OCCUPIED_*      → ARREARS           (past-due, triggered by nightly job)
    ARREARS         → OCCUPIED_PARTIAL  (partial payment on arrears)
    ARREARS         → OCCUPIED_PAID     (full arrears cleared)
    ARREARS         → VACANT            (eviction / move-out)
"""
from decimal import Decimal

from django.db import models

from .models import Unit, UnitStatus

# Valid origin → destination transitions.
VALID_TRANSITIONS: dict[str, set[str]] = {
    UnitStatus.VACANT: {UnitStatus.OCCUPIED_UNPAID},
    UnitStatus.OCCUPIED_UNPAID: {
        UnitStatus.OCCUPIED_PARTIAL,
        UnitStatus.OCCUPIED_PAID,
        UnitStatus.ARREARS,
        UnitStatus.VACANT,
    },
    UnitStatus.OCCUPIED_PARTIAL: {
        UnitStatus.OCCUPIED_PAID,
        UnitStatus.ARREARS,
        UnitStatus.VACANT,
    },
    UnitStatus.OCCUPIED_PAID: {
        UnitStatus.OCCUPIED_UNPAID,
        UnitStatus.ARREARS,
        UnitStatus.VACANT,
    },
    UnitStatus.ARREARS: {
        UnitStatus.OCCUPIED_PARTIAL,
        UnitStatus.OCCUPIED_PAID,
        UnitStatus.VACANT,
    },
}


class InvalidStatusTransition(Exception):
    """Raised when a status change violates the allowed transitions."""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


def transition_status(unit: Unit, new_status: str) -> Unit:
    """
    Transition a unit to a new status, enforcing the valid transition graph.

    Raises InvalidStatusTransition if the move is not allowed.
    """
    if new_status == unit.status:
        return unit  # no-op

    allowed = VALID_TRANSITIONS.get(unit.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransition(unit.status, new_status)

    unit.status = new_status
    unit.save(update_fields=["status", "updated_at"])
    return unit


def move_in(unit: Unit) -> Unit:
    """Mark a unit as occupied (unpaid) when a tenant moves in."""
    if unit.status != UnitStatus.VACANT:
        raise InvalidStatusTransition(unit.status, UnitStatus.OCCUPIED_UNPAID)
    return transition_status(unit, UnitStatus.OCCUPIED_UNPAID)


def move_out(unit: Unit) -> Unit:
    """Mark a unit as vacant when a tenant moves out."""
    if unit.status == UnitStatus.VACANT:
        raise InvalidStatusTransition(unit.status, UnitStatus.VACANT)
    return transition_status(unit, UnitStatus.VACANT)


def has_unsettled_earlier_months(unit: Unit) -> bool:
    """True when the unit's tenant still owes for a month before this one.

    Kept separate from the status rule so the arrears sweep and the integrity
    check can ask the same question the badge answers.
    """
    from django.utils import timezone

    from apps.payments.models import Arrears
    from apps.payments.services import available_credit
    from apps.tenants.models import Tenant, TenantStatus

    tenant_ids = list(
        Tenant.objects
        .filter(unit=unit, status__in=[TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN])
        .values_list("id", flat=True)
    )
    if not tenant_ids:
        return False

    today = timezone.localdate()
    earlier = models.Q(period_year__lt=today.year) | models.Q(
        period_year=today.year, period_month__lt=today.month
    )
    open_by_tenant = {}
    rows = (
        Arrears.objects
        .filter(earlier, tenant_id__in=tenant_ids, is_cleared=False, balance__gt=0)
        .values_list("tenant_id", "balance")
    )
    for tenant_id, balance in rows:
        open_by_tenant[tenant_id] = open_by_tenant.get(tenant_id, Decimal("0")) + balance
    if not open_by_tenant:
        return False

    # An open earlier row is not the same thing as money owed. Cash is
    # allocated to the month it arrived, not to the oldest debt — that is what
    # the statement reconciliations restated it to — so a tenant who overpaid
    # this month still leaves last month's row open while being square, or
    # ahead, overall. DON2A closed August 250 in credit and read "in arrears".
    # Net the open rows against credit the tenant is actually carrying; a
    # shortfall is real debt, and MCG10's 43,800 with nothing against it still
    # is one.
    tenants = Tenant.objects.in_bulk(open_by_tenant)
    return any(
        owed > available_credit(tenants[tenant_id])
        for tenant_id, owed in open_by_tenant.items()
    )


def recalculate_unit_status(
    unit: Unit, amount_paid: Decimal, *, obligation: Decimal | None = None
) -> Unit:
    """
    Recalculate status based on how much has been paid for the current period.

    Called by the payment processing service (Day 4). Logic:
    - amount_paid == 0     → OCCUPIED_UNPAID
    - 0 < amount_paid < rent → OCCUPIED_PARTIAL
    - amount_paid >= rent  → OCCUPIED_PAID

    ``obligation`` is the figure the payment should be measured against. Callers
    that know the true period obligation — rent plus VAT for a commercial unit,
    which is what the tenant actually pays — pass it explicitly; otherwise the
    unit's base rent is used and a commercial tenant paying in full would never
    reach OCCUPIED_PAID.
    """
    if unit.status == UnitStatus.VACANT:
        return unit  # can't recalculate a vacant unit

    # Debt carried from an earlier month outranks how this one is going. A
    # tenant who pays August in full while still owing July is in arrears, not
    # "paid" — MCG10 read Paid on the units board while carrying 43,800 forward,
    # because the rule only ever looked at the current period. This is also the
    # only thing that ever sets ARREARS: the status existed, the badge existed
    # and the dashboard counted it, but nothing outside seed data assigned it.
    if has_unsettled_earlier_months(unit):
        new = UnitStatus.ARREARS
        if new != unit.status:
            unit.status = new
            unit.save(update_fields=["status", "updated_at"])
        return unit

    rent = obligation if obligation is not None else unit.monthly_rent
    if amount_paid <= 0:
        new = UnitStatus.OCCUPIED_UNPAID
    elif amount_paid < rent:
        new = UnitStatus.OCCUPIED_PARTIAL
    else:
        new = UnitStatus.OCCUPIED_PAID

    if new != unit.status:
        unit.status = new
        unit.save(update_fields=["status", "updated_at"])
    return unit
