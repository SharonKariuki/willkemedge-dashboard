"""
Set the rent on one month a letting has already been charged — or raise it.

Editing a tenant's rent, or a combined space's, only moves the NEXT charge.
A month already raised at the wrong figure stays wrong; this restates it:

  * MCG10 October 2026 was raised at 25,000; the agreed rent is 30,000.
  * Sidai Lonestar Healthcare (MCG05 + MCG06) October was raised at 86,500,
    without MCG06; November at 185,260 with the Office & Physio units in it.
  * MCF12 (Sidai's office until 17 Oct) has no October charge at all.

``--rent`` is the VAT-EXCLUSIVE rent, as on the tenant card; VAT is worked
out the same way the rent run works it out (16% on a commercial letting,
none on a residential or VAT-exempt one). A month with no charge is raised,
never before the letting's first rent month. The row is re-saved, so the
accrual ledger re-posts it, and its balance is worked out again from the
money already on it. A month raised here draws on banked credit as the rent
run's would (Ignite paid October to December ahead).

Refused: an opening-balance row (that is not a month's rent), and a figure
below what credit notes have already taken off the month.

Preview is the DEFAULT: the change runs and is rolled back. ``--apply`` keeps it.

Usage (Render Shell):
    python manage.py set_rent_month MCG10 2026-10 --rent 30000
    python manage.py set_rent_month MCF12 2026-10 --rent 50655 --tenant-id 166 --apply
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

ZERO = Decimal("0")


class _Rollback(Exception):
    pass


def _period(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-"))
    except ValueError:
        raise CommandError(f"Month must be YYYY-MM, not {value!r}") from None
    if not 1 <= month <= 12:
        raise CommandError(f"Month must be YYYY-MM, not {value!r}")
    return year, month


def _amount(value: str) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        raise CommandError(f"--rent must be an amount, not {value!r}") from None
    if amount <= 0:
        raise CommandError("--rent must be more than 0.")
    return amount.quantize(Decimal("0.01"))


class Command(BaseCommand):
    help = "Set (or raise) one month's rent charge for a letting (preview unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("unit", help="Unit label of the letting, e.g. MCG10")
        parser.add_argument("month", help="The month, YYYY-MM")
        parser.add_argument("--rent", required=True, help="VAT-exclusive rent for the month")
        parser.add_argument(
            "--tenant-id", type=int,
            help="The tenancy, when it is not the unit's current one (a moved-out letting)",
        )
        parser.add_argument("--apply", action="store_true", help="Keep the change (default: preview)")

    def handle(self, *args, unit, month, rent, tenant_id, apply, **options):
        year, mon = _period(month)
        rent = _amount(rent)
        tenant = self._tenant(unit, tenant_id)

        self.stdout.write(f"{unit} {mon}/{year}: {tenant} — {'APPLY' if apply else 'PREVIEW (rolled back)'}")
        try:
            with transaction.atomic():
                self._set(tenant, year, mon, rent)
                if not apply:
                    raise _Rollback
        except _Rollback:
            self.stdout.write("Preview only — nothing was kept. Run again with --apply.")

    def _tenant(self, unit, tenant_id):
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        qs = Tenant.objects.select_related("unit")
        if tenant_id is not None:
            tenant = qs.filter(pk=tenant_id).first()
            if tenant is None or tenant.unit.label != unit:
                raise CommandError(
                    f"Tenant {tenant_id} is not a letting of {unit}. Tenant ids are not "
                    f"portable between databases. Nothing was written."
                )
            return tenant
        current = list(qs.filter(unit__label=unit, status__in=CURRENT_STATUSES))
        if len(current) != 1:
            raise CommandError(
                f"{unit}: expected one current tenant, found {len(current)}. "
                f"Pass --tenant-id for a moved-out letting. Nothing was written."
            )
        return current[0]

    def _set(self, tenant, year, month, rent):
        from django.db.models import Sum

        from apps.accounts import audit
        from apps.payments.models import Arrears, CreditStatus
        from apps.payments.monthly_ledger import OPENING_MARKER
        from apps.payments.services import _update_arrears, expected_vat_for

        vat = expected_vat_for(tenant, rent)
        row = (
            Arrears.objects.select_for_update()
            .filter(tenant=tenant, period_year=year, period_month=month)
            .first()
        )
        if row is None:
            first = tenant.first_rent_period
            if first and (year, month) < first:
                raise CommandError(
                    f"{tenant}'s rent starts {first[1]}/{first[0]}; {month}/{year} cannot be charged."
                )
            row = Arrears.objects.create(
                tenant=tenant, period_year=year, period_month=month,
                expected_rent=rent, expected_vat=vat,
                amount_paid=ZERO, balance=rent + vat, is_cleared=False,
            )
            old = None
            self.stdout.write(f"  raised: rent {rent:,.2f} + VAT {vat:,.2f} = {rent + vat:,.2f}")
        else:
            if OPENING_MARKER in (row.waive_notes or ""):
                raise CommandError(f"{month}/{year} is an opening balance, not a month's rent. Nothing was written.")
            credited = row.credit_notes.filter(status=CreditStatus.ISSUED).aggregate(t=Sum("amount"))["t"] or ZERO
            if rent + vat < credited:
                raise CommandError(
                    f"Credit notes have already taken {credited:,.2f} off {month}/{year}; "
                    f"the month cannot be set below that. Nothing was written."
                )
            old = (row.expected_rent, row.expected_vat or ZERO)
            if old == (rent, vat):
                self.stdout.write(f"  already rent {rent:,.2f} + VAT {vat:,.2f} — nothing to change")
                return
            self.stdout.write(
                f"  rent {old[0]:,.2f} + VAT {old[1]:,.2f} -> rent {rent:,.2f} + VAT {vat:,.2f}"
            )
            row.expected_rent, row.expected_vat = rent, vat
            row.save(update_fields=["expected_rent", "expected_vat", "updated_at"])

        row = _update_arrears(tenant, month, year)
        if old is None:
            # As the rent run does for a month it raises: money already banked
            # (a quarter paid ahead) pays for it, overpaid rent first, then the
            # tenant's numbered credits.
            from apps.payments.credits import apply_account_credits
            from apps.payments.services import apply_available_credit

            row = apply_available_credit(row)
            apply_account_credits(row)
            row.refresh_from_db()
        self.stdout.write(f"  month balance now {row.balance:,.2f}")
        audit.record(
            action="arrears.set_rent",
            object_type="tenant",
            object_id=tenant.pk,
            object_label=str(tenant),
            summary=f"Rent {month}/{year} set to {rent} + VAT {vat}" + (" (raised)" if old is None else ""),
            old_values={"expected_rent": str(old[0]), "expected_vat": str(old[1])} if old else None,
            new_values={"expected_rent": str(rent), "expected_vat": str(vat)},
        )
