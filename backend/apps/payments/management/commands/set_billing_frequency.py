"""
Switch a letting between monthly and quarterly billing, and raise what is due.

Ignite (MCG07) is billed a calendar quarter in advance: the 7 Oct 2026
statement charges October, November and December together, 3 x 69,600 =
208,800. Setting the letting to quarterly makes the rent run raise to the end
of each quarter (billing_calendar.billed_through); this command then raises the
months the new setting says are already due, so the statement agrees today
rather than after the next 25th.

Each month is still its own Arrears row at the letting's monthly rent, so the
VAT on each, the accrual ledger (which books a charge to its own period) and
the arrears report (which only counts periods up to the current month) are all
unchanged. Going back to monthly raises nothing and removes nothing: months
already raised for the rest of a quarter stay billed.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py set_billing_frequency MCG07 quarterly
    python manage.py set_billing_frequency MCG07 quarterly --apply
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Set a letting to monthly or quarterly billing and raise what that makes due. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("unit", help="Unit label, e.g. MCG07.")
        parser.add_argument("frequency", choices=["monthly", "quarterly"])
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **opts):
        from apps.payments.billing_calendar import billed_through
        from apps.payments.models import Arrears
        from apps.payments.tasks import billing_floor, periods_due, raise_due_periods
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        label = opts["unit"].strip().upper()
        frequency = opts["frequency"]
        tenants = list(
            Tenant.objects.filter(unit__label__iexact=label, status__in=CURRENT_STATUSES)
            .select_related("unit")
        )
        if len(tenants) != 1:
            raise CommandError(
                f"Expected one current tenant on {label}, found {len(tenants)}. Nothing was written."
            )
        tenant = tenants[0]
        self.stdout.write(f"{label} {tenant.full_name}: {tenant.billing_frequency} -> {frequency}")

        was = tenant.billing_frequency
        tenant.billing_frequency = frequency
        have = set(Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month"))
        through = billed_through(tenant)
        due = [p for p in periods_due(tenant, billing_floor(), through) if p not in have]
        for year, month in due:
            self.stdout.write(f"  raise {month:02d}/{year}: {tenant.monthly_rent} + VAT")
        if not due:
            self.stdout.write(f"  nothing further to raise (billed through {through[1]:02d}/{through[0]})")

        if not opts["apply"]:
            tenant.billing_frequency = was
            changes = int(was != frequency) + len(due)
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {changes} change(s) would be written. Re-run with --apply."
            ))
            return

        with transaction.atomic():
            tenant.save(update_fields=["billing_frequency", "updated_at"])
            raised, _drew = raise_due_periods(tenant)
        self.stdout.write(self.style.SUCCESS(
            f"\nApplied: {label} is {frequency}; {raised} month(s) raised."
        ))
