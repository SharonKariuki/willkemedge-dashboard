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


def recalculate_unit_status(unit: Unit, amount_paid: Decimal) -> Unit:
    """
    Recalculate status based on how much has been paid for the current period.

    Called by the payment processing service (Day 4). Logic:
    - amount_paid == 0     → OCCUPIED_UNPAID
    - 0 < amount_paid < rent → OCCUPIED_PARTIAL
    - amount_paid >= rent  → OCCUPIED_PAID
    """
    if unit.status == UnitStatus.VACANT:
        return unit  # can't recalculate a vacant unit

    rent = unit.monthly_rent
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
