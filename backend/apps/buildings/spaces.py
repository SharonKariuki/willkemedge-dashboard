"""
Combined commercial spaces — several units let and billed as one.

The units must be vacant commercial units in the same building; they need not
be next to each other or on the same floor. A hospital that takes MCG05–MCG08
pays one rent, on one paybill account, under
one tenancy. Rather than a second tenancy model, the space is the head unit
plus the units that point at it through ``Unit.combined_into``:

  * the tenancy stays on the head, so billing, statements, arrears, credits and
    the ledger — all of which hang off ``Tenant.unit`` — are unchanged;
  * the other units mirror the head's status (``Unit.save``), so occupancy
    counts them as let and none of them can be let separately;
  * a payment quoting any unit in the space reaches the tenant (the matcher
    resolves a member to its head);
  * the rent that bills is still ``Tenant.monthly_rent``. Adding or removing a
    unit moves it by that unit's standing rent unless the landlord agrees a
    different figure, and the change is written to the financial audit log.

The rent is picked up by the next billing run. Months already charged are not
restated — the same rule as editing a tenant's rent by hand.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Unit, UnitClassification, UnitStatus

ZERO = Decimal("0")


@dataclass
class SpaceChange:
    head: Unit
    added: list[Unit]
    removed: list[Unit]
    tenant: object | None
    old_rent: Decimal | None
    new_rent: Decimal | None


def _current_tenant(unit: Unit):
    from apps.tenants.models import Tenant, TenantStatus

    return (
        Tenant.objects.select_for_update()
        .filter(unit=unit, status__in=[TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN])
        .first()
    )


def suggested_rent(current: Decimal, add: list[Unit], remove: list[Unit]) -> Decimal:
    """Current rent moved by the standing rent of each unit taken or given up.

    Starting from what the tenant pays rather than re-adding every unit's
    standing rent keeps any discount already agreed on the space.
    """
    rent = current + sum((u.monthly_rent for u in add), ZERO) - sum((u.monthly_rent for u in remove), ZERO)
    return max(rent, ZERO)


@transaction.atomic
def reconfigure_space(
    head: Unit,
    *,
    add: list[Unit] = (),
    remove: list[Unit] = (),
    monthly_rent: Decimal | None = None,
    actor=None,
) -> SpaceChange:
    """Add units to, or take units out of, the space headed by ``head``.

    ``monthly_rent`` is the agreed base rent (VAT-exclusive) for the space
    after the change. Omitted, it is suggested from the units' standing rents.
    Raises ``ValidationError`` and changes nothing if any rule is broken.
    """
    from apps.accounts import audit

    head = Unit.objects.select_for_update().get(pk=head.pk)
    add_ids = {u.pk for u in add}
    remove_ids = {u.pk for u in remove}
    add = list(Unit.objects.select_for_update().filter(pk__in=add_ids).order_by("label"))
    remove = list(Unit.objects.select_for_update().filter(pk__in=remove_ids).order_by("label"))

    errors = []
    if not add and not remove:
        errors.append("Choose at least one unit to add or remove.")
    if add_ids & remove_ids:
        errors.append("A unit cannot be added and removed in the same change.")
    if head.combined_into_id:
        errors.append(
            f"{head.label} is part of {head.combined_into.label}'s space — change that space instead."
        )
    if head.classification != UnitClassification.BUSINESS:
        errors.append("Only commercial units can be combined.")

    for unit in add:
        if unit.pk == head.pk:
            errors.append(f"{unit.label} is already the head of this space.")
        elif unit.building_id != head.building_id:
            errors.append(f"{unit.label} is in another property.")
        elif unit.classification != UnitClassification.BUSINESS:
            errors.append(f"{unit.label} is not a commercial unit.")
        elif unit.combined_into_id == head.pk:
            errors.append(f"{unit.label} is already part of this space.")
        elif unit.combined_into_id:
            errors.append(f"{unit.label} is already part of {unit.combined_into.label}'s space.")
        elif unit.combined_units.exists():
            errors.append(f"{unit.label} heads its own combined space — split it first.")
        elif _current_tenant(unit) is not None:
            errors.append(f"{unit.label} has a current tenant — move them out first.")
        elif unit.status != UnitStatus.VACANT:
            errors.append(f"{unit.label} is not vacant ({unit.get_status_display()}).")

    for unit in remove:
        if unit.combined_into_id != head.pk:
            errors.append(f"{unit.label} is not part of {head.label}'s space.")

    if monthly_rent is not None and monthly_rent < 0:
        errors.append("Rent cannot be negative.")
    if errors:
        raise ValidationError(errors)

    before = head.space_label
    for unit in add:
        unit.combined_into = head
        unit.status = head.status
        unit.save(update_fields=["combined_into", "status", "updated_at"])
    for unit in remove:
        # Nobody holds a member unit on its own, so leaving the space frees it.
        unit.combined_into = None
        unit.status = UnitStatus.VACANT
        unit.save(update_fields=["combined_into", "status", "updated_at"])
    after = head.space_label

    tenant = _current_tenant(head)
    old_rent = new_rent = None
    if tenant is not None:
        old_rent = tenant.monthly_rent
        new_rent = monthly_rent if monthly_rent is not None else suggested_rent(old_rent, add, remove)
        if new_rent != old_rent:
            tenant.monthly_rent = new_rent
            tenant.save(update_fields=["monthly_rent", "updated_at"])

    audit.record(
        action="unit.space_reconfigure",
        object_type="tenant" if tenant else "unit",
        object_id=tenant.pk if tenant else head.pk,
        summary=(
            f"Space {before} -> {after}"
            + (f"; rent {old_rent} -> {new_rent}" if tenant and old_rent != new_rent else "")
        ),
        actor=actor,
        old_values={"space": before, **({"monthly_rent": old_rent} if tenant else {})},
        new_values={"space": after, **({"monthly_rent": new_rent} if tenant else {})},
    )
    return SpaceChange(head, add, remove, tenant, old_rent, new_rent)
