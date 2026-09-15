"""
Put deposits that exist only on the tenant card onto the books.

Until editing a deposit booked it, ``Tenant.deposit_paid`` could be changed —
by the edit form, ``set_residential_deposits`` or ``apply_matasia_answers`` —
without a DEPOSIT payment or journal behind it. The card then showed a deposit
the statement and 2100 (Tenant Security Deposits Held) did not, which is how an
edited deposit looked as though it had never been saved.

What it changes
---------------
A tenancy whose card shows MORE than the books hold gets a DEPOSIT payment for
the difference (DR 1030 / CR 2100), dated ``--on`` (default today). Books are
read the way ``deposit_held_on_books`` reads them: unvoided DEPOSIT payments
plus any cutover ``opening_deposit`` journal, so a cutover deposit is not
booked a second time.

What it will not change
-----------------------
A tenancy whose books hold MORE than the card is REPORTED only. That is either
a card someone under-typed or a deposit refunded outside the system, and only
the director can say which — edit the deposit on the tenant page to settle it.

Moved-out tenancies are skipped.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe:
once booked, the card and the books agree and the tenancy drops off the list.

Usage:
    python manage.py sync_deposit_bookings
    python manage.py sync_deposit_bookings --apply
    python manage.py sync_deposit_bookings --apply --on 2026-09-01
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.deposits import deposit_held_on_books

ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = (
        "Book DEPOSIT payments for deposits recorded on the tenant card but "
        "missing from the ledger. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument(
            "--on", default=None,
            help="Date to book the missing deposits on (YYYY-MM-DD). Defaults to today.",
        )

    def handle(self, *args, **opts):
        from apps.payments.models import PaymentSource
        from apps.tenants.models import Tenant, TenantStatus
        from apps.tenants.services import _book_deposit

        try:
            on = _dt.date.fromisoformat(opts["on"]) if opts["on"] else _dt.date.today()
        except ValueError as exc:
            raise CommandError(f"--on must be YYYY-MM-DD, got {opts['on']!r}") from exc

        tenants = (
            Tenant.objects.exclude(status=TenantStatus.MOVED_OUT)
            .select_related("unit", "unit__building")
            .order_by("unit__building__code", "unit__label")
        )

        missing, excess = [], []
        for tenant in tenants:
            card = Decimal(tenant.deposit_paid or ZERO)
            books = deposit_held_on_books(tenant)
            if card > books:
                missing.append((tenant, card, books))
            elif card < books:
                excess.append((tenant, card, books))

        self.stdout.write(self.style.MIGRATE_HEADING("\nSecurity deposits — card vs books (2100)"))

        if missing:
            self.stdout.write(f"\nOn the card but not the books ({len(missing)}) — will be booked on {on}:")
            for tenant, card, books in missing:
                self.stdout.write(
                    f"  {self._label(tenant):<10} {tenant.full_name:<28} "
                    f"card {card:>12,.2f}  books {books:>12,.2f}  book {card - books:>12,.2f}"
                )

        if excess:
            self.stdout.write(self.style.WARNING(
                f"\nBooks hold more than the card ({len(excess)}) — REPORTED ONLY, "
                f"edit the deposit on the tenant page to settle:"
            ))
            for tenant, card, books in excess:
                self.stdout.write(
                    f"  {self._label(tenant):<10} {tenant.full_name:<28} "
                    f"card {card:>12,.2f}  books {books:>12,.2f}"
                )

        if not missing:
            self.stdout.write(self.style.SUCCESS("\nNothing to book."))
            return

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {len(missing)} deposit(s) would be booked. Re-run with --apply."
            ))
            return

        with transaction.atomic():
            for tenant, card, books in missing:
                _book_deposit(
                    tenant, card - books, on=on, source=PaymentSource.CASH, reference="",
                    notes="Deposit on the tenant card, booked by sync_deposit_bookings.",
                    created_by=None,
                )

        self.stdout.write(self.style.SUCCESS(f"\nBooked {len(missing)} deposit(s)."))

    def _label(self, tenant):
        return tenant.unit.label if tenant.unit else "(no unit)"
