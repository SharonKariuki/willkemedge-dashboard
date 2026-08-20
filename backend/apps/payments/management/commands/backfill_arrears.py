"""
Raise the rent months that were never billed.

There is no Celery beat in production — a free external scheduler calls
`/api/payments/cron/monthly-arrears/` (see cron_views) — and it has not been
firing. `generate_monthly_arrears` now catches up every month a tenant is short
of rather than only looking at the current one, but running it blind would raise
a large amount of debt in one go, so this wraps it in a preview.

Preview is the DEFAULT. Nothing is written without --apply.

Usage (Render Shell):
    python manage.py backfill_arrears            # what would be raised
    python manage.py backfill_arrears --apply    # raise it

Fix the schedule as well, or the gap simply reopens next month.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = "Raise Arrears rows for every rent month that was never billed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Raise the rows. Without this the command only previews them.",
        )

    def handle(self, *args, **opts):
        from apps.payments.models import Arrears
        from apps.payments.services import expected_vat_for
        from apps.payments.tasks import billing_floor, generate_monthly_arrears, periods_due
        from apps.tenants.models import Tenant, TenantStatus

        now = timezone.now()
        through = (now.year, now.month)
        floor = billing_floor()

        if floor is None:
            self.stdout.write(self.style.WARNING(
                "No opening-balance entries found — billing starts at each "
                "tenant's move-in month."
            ))
        else:
            self.stdout.write(f"Billing from {floor[1]}/{floor[0]} through {through[1]}/{through[0]}.")

        pending = []
        for tenant in Tenant.objects.filter(
            status=TenantStatus.ACTIVE
        ).select_related("unit", "unit__building"):
            have = set(
                Arrears.objects.filter(tenant=tenant)
                .values_list("period_year", "period_month")
            )
            missing = [p for p in periods_due(tenant, floor, through) if p not in have]
            if missing:
                obligation = tenant.monthly_rent + expected_vat_for(tenant, tenant.monthly_rent)
                pending.append((tenant, missing, obligation))

        self._report(pending)

        if not pending:
            return

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nPreview only — nothing written. Re-run with --apply to raise these."
            ))
            return

        with db_transaction.atomic():
            raised = generate_monthly_arrears()

        self.stdout.write(self.style.SUCCESS(f"\nRaised {raised} arrears row(s)."))

    def _report(self, pending):
        if not pending:
            self.stdout.write(self.style.SUCCESS("\nNothing to raise — every active tenant is billed up to date."))
            return

        self.stdout.write(
            f"\n{'TENANT':<30} {'UNIT':<8} {'MONTHS MISSING':<22} {'PER MONTH':>11} {'TOTAL':>12}"
        )
        self.stdout.write("-" * 88)

        total = ZERO
        zero_rent = []
        for tenant, missing, obligation in sorted(
            pending, key=lambda r: -(r[2] * len(r[1]))
        ):
            amount = obligation * len(missing)
            total += amount
            months = ", ".join(f"{m}/{y}" for y, m in missing)
            unit = getattr(tenant.unit, "label", "—")
            self.stdout.write(
                f"{str(tenant)[:30]:<30} {unit:<8} {months[:22]:<22} "
                f"{obligation:>11,.2f} {amount:>12,.2f}"
            )
            if obligation <= 0:
                zero_rent.append((tenant, unit))

        self.stdout.write("-" * 88)
        self.stdout.write(
            f"{len(pending)} tenant(s) · "
            f"{sum(len(m) for _, m, _ in pending)} row(s) · {total:,.2f} to be raised"
        )

        if zero_rent:
            # These raise a row for nothing, so the tenant still reads as owing
            # zero and every payment they make banks as credit.
            self.stdout.write(self.style.WARNING(
                f"\n{len(zero_rent)} tenant(s) have no rent on file — they will be "
                f"billed 0.00 and stay invisible to the arrears report:"
            ))
            for tenant, unit in zero_rent:
                self.stdout.write(f"  {str(tenant)[:40]:<40} {unit}")
