"""
Re-derive every unit's status from what its tenant actually owes.

The nightly sweep that normally does this runs off the cron endpoint, which has
been failing at its guard clause since July, so statuses on the units board have
been stale for a month. This is the same work, runnable by hand.

Status only ever described the current period, so a tenant who paid this month
in full while owing an earlier one showed as "Paid". Since that rule now
considers earlier months, a unit with carried debt lands on ARREARS — a status
that existed, had a badge and was counted on the dashboard, but which nothing
outside seed data had ever assigned.

    python manage.py recalculate_unit_statuses          # preview
    python manage.py recalculate_unit_statuses --apply
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Re-derive unit statuses from current balances. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument(
            "--building", default=None,
            help="Limit to one building code, e.g. MC. Default: every building.",
        )

    def handle(self, *args, **opts):
        from decimal import Decimal

        from django.utils import timezone

        from apps.buildings.models import Unit, UnitStatus
        from apps.buildings.services import has_unsettled_earlier_months
        from apps.payments.services import expected_vat_for, rent_payments_for
        from apps.tenants.models import Tenant, TenantStatus

        apply = opts["apply"]
        now = timezone.now()

        units = Unit.objects.select_related("building").order_by("building__code", "label")
        if opts["building"]:
            units = units.filter(building__code=opts["building"])

        changes, unchanged = [], 0
        for unit in units:
            tenant = (
                Tenant.objects
                .filter(unit=unit, status__in=[TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN])
                .first()
            )

            if tenant is None:
                # No live tenancy is the definition of vacant, whatever the
                # board currently says.
                wanted = UnitStatus.VACANT
            elif has_unsettled_earlier_months(unit):
                wanted = UnitStatus.ARREARS
            else:
                paid = sum(
                    (p.amount for p in rent_payments_for(tenant, now.month, now.year)),
                    Decimal("0.00"),
                )
                obligation = tenant.monthly_rent + expected_vat_for(tenant, tenant.monthly_rent)
                if paid <= 0:
                    wanted = UnitStatus.OCCUPIED_UNPAID
                elif paid < obligation:
                    wanted = UnitStatus.OCCUPIED_PARTIAL
                else:
                    wanted = UnitStatus.OCCUPIED_PAID

            # A unit taken out of service is a deliberate state, not something
            # a payment sweep should quietly overwrite.
            if unit.status == UnitStatus.UNDER_MAINTENANCE:
                unchanged += 1
                continue

            if unit.status == wanted:
                unchanged += 1
                continue

            who = tenant.full_name if tenant else "no tenant"
            changes.append((unit, wanted, who))

        for unit, wanted, who in changes:
            self.stdout.write(
                f"  {unit.building.code} {unit.label:<8} {unit.status:>17} -> {wanted:<17} ({who})"
            )
            if apply:
                unit.status = wanted
                # A vacant unit carrying its last tenant's rent overstates the
                # rent roll and shows a figure on a card that reads "No tenant".
                if wanted == UnitStatus.VACANT and unit.monthly_rent:
                    unit.monthly_rent = Decimal("0.00")
                    unit.save(update_fields=["status", "monthly_rent", "updated_at"])
                else:
                    unit.save(update_fields=["status", "updated_at"])

        if not changes:
            self.stdout.write(self.style.SUCCESS(f"Every status already correct ({unchanged} units)."))
        elif apply:
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {len(changes)} unit(s); {unchanged} already correct."))
        else:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {len(changes)} unit(s) would change, {unchanged} already correct. "
                f"Re-run with --apply."
            ))
