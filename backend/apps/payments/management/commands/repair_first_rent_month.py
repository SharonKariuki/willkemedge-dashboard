"""
Re-book new tenants whose deposit and first rent landed as the wrong month's rent.

Two lettings taken in October 2026 went wrong the same way:

  * The rent run charged a month the tenant does not pay for — the move-in
    month, or (before this fix) the month the money arrived in.
  * The bank credit that carried the deposit was assigned whole as rent, and
    the cash deposit keyed in at registration was then voided as a "double".
    The books hold no deposit; the deposit sits on that wrong month as rent.

MR203  Samuel Mogoko. Keys 31 Oct, first rent November. Paid 53,000 in three
       credits = rent deposit 25,000 + service charge & water deposit 3,000 +
       November rent 25,000 (27,000 due, so 2,000 still owing). All 53,000 sat
       on an October charge of 27,000.
DON2A  Alex Mureithi Njue. Moves in 1 Nov. The 20,000 credit is the deposit;
       it sat on an October rent obligation the payment itself created.
       November rent (20,000) is owed in full.

For each letting, in one transaction: send its bank credits back to
Reconciliation (``void_and_requeue_credit``), set the first rent month, remove
the charges before it — only once no money is left on them — and assign each
credit again with its deposit / rent split. Removing a charge deletes its
Arrears row, and the ledger signal reverses its journal.

MR308 is NOT here. Its September was re-raised by the catch-up run on 25 Oct
and was cancelled the same day with credit note CN-00001; that account is
right as it stands.

Safety
------
Preview is the DEFAULT: the whole repair runs and is rolled back, so the
preview shows the real outcome. ``--apply`` keeps it. Every letting is checked
against the shape it is expected to have and refused on any surprise, and the
result must match the target below or nothing is kept. ``--unit`` limits the
run to one letting, so each can be applied once the landlord confirms it.

Usage (Render Shell):
    python manage.py repair_first_rent_month
    python manage.py repair_first_rent_month --unit MR203 --apply
"""
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Credit:
    transaction_id: str
    amount: Decimal
    #: How much of it is deposit; the rest is rent.
    deposit: Decimal


@dataclass(frozen=True)
class Fix:
    unit: str
    tenant_name: str
    #: None leaves it on the move-in month.
    first_rent_month: dt.date | None
    credits: tuple[Credit, ...]
    #: What the account must hold afterwards.
    deposit_held: Decimal
    #: {(year, month): (rent paid, balance)} for every charge left.
    rent_rows: dict = field(default_factory=dict)


FIXES = (
    Fix(
        unit="MR203",
        tenant_name="Samuel Mogoko",
        first_rent_month=dt.date(2026, 11, 1),
        credits=(
            Credit("CB0403388_15102026_2", Decimal("25000"), deposit=Decimal("25000")),
            Credit("CB0385042_23102026_2", Decimal("27000"), deposit=Decimal("3000")),
            Credit("CB0387303_23102026_2", Decimal("1000"), deposit=ZERO),
        ),
        deposit_held=Decimal("28000"),
        rent_rows={(2026, 11): (Decimal("25000"), Decimal("2000"))},
    ),
    Fix(
        unit="DON2A",
        tenant_name="Alex Mureithi Njue",
        first_rent_month=None,
        credits=(
            Credit("CB0795825_25102026_2", Decimal("20000"), deposit=Decimal("20000")),
        ),
        deposit_held=Decimal("20000"),
        rent_rows={},
    ),
)


class _Preview(Exception):
    """Raised to roll a preview back once it has been reported."""


class Command(BaseCommand):
    help = "Re-book new tenants' deposit + first rent and drop the month they do not owe."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Keep the repair. Default is a preview.")
        parser.add_argument("--unit", help="Only this unit label, e.g. MR203.")

    def handle(self, *args, **opts):
        fixes = [f for f in FIXES if not opts["unit"] or f.unit == opts["unit"]]
        if not fixes:
            raise CommandError(f"No repair is defined for unit {opts['unit']}.")
        for fix in fixes:
            try:
                with db_transaction.atomic():
                    self._repair(fix)
                    if not opts["apply"]:
                        raise _Preview
            except _Preview:
                self.stdout.write(self.style.WARNING(f"  {fix.unit}: PREVIEW — rolled back."))
            else:
                self.stdout.write(self.style.SUCCESS(f"  {fix.unit}: applied."))
        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("\nNothing written. Re-run with --apply to keep it."))

    # -----------------------------------------------------------------------

    def _tenant(self, fix):
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        tenant = (
            Tenant.objects.select_related("unit")
            .filter(unit__label=fix.unit, status__in=CURRENT_STATUSES)
            .first()
        )
        if tenant is None:
            raise CommandError(f"{fix.unit}: no current tenant.")
        # Tenant ids differ between live and every copy of it, so the letting
        # is found by unit and confirmed by name.
        if tenant.full_name.strip().lower() != fix.tenant_name.lower():
            raise CommandError(f"{fix.unit}: tenant is {tenant.full_name}, expected {fix.tenant_name}.")
        return tenant

    def _event(self, tenant, credit):
        from apps.payments.models import CoopIpnEvent, CoopIpnStatus

        event = CoopIpnEvent.objects.filter(transaction_id=credit.transaction_id).first()
        if event is None:
            raise CommandError(f"Bank credit {credit.transaction_id} not found.")
        if event.amount != credit.amount:
            raise CommandError(
                f"{credit.transaction_id} is KES {event.amount:,.2f}, expected {credit.amount:,.2f}."
            )
        if event.status != CoopIpnStatus.RECORDED or event.payment is None \
                or event.payment.tenant_id != tenant.pk:
            raise CommandError(f"{credit.transaction_id} is not booked to {tenant.full_name}.")
        return event

    def _report(self, tenant, heading):
        from apps.payments.models import Arrears, Payment
        from apps.tenants.deposits import deposit_held_on_books

        self.stdout.write(f"  {heading}:")
        for row in Arrears.objects.filter(tenant=tenant).order_by("period_year", "period_month"):
            self.stdout.write(
                f"    charge {row.period_month:>2}/{row.period_year}  rent {row.expected_rent:>10,.2f}  "
                f"paid {row.amount_paid:>10,.2f}  credit {row.credit_applied:>9,.2f}  "
                f"balance {row.balance:>9,.2f}"
            )
        for pay in Payment.objects.filter(tenant=tenant, voided_at__isnull=True).order_by("pk"):
            self.stdout.write(
                f"    #{pay.pk:<6} {pay.payment_type:<8} {pay.amount:>10,.2f}  "
                f"for {pay.period_month:>2}/{pay.period_year}  {pay.reference}"
            )
        self.stdout.write(f"    deposit on the books {deposit_held_on_books(tenant):,.2f}")

    def _repair(self, fix):
        from apps.accounts import audit
        from apps.payments.models import Arrears
        from apps.payments.services import (
            assign_unmatched_credit,
            rent_payments_for,
            void_and_requeue_credit,
        )
        from apps.tenants.deposits import deposit_held_on_books

        tenant = self._tenant(fix)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{fix.unit} — {tenant.full_name} (tenant #{tenant.pk}), move-in {tenant.move_in_date}"
        ))
        self._report(tenant, "before")
        events = [self._event(tenant, c) for c in fix.credits]

        # 1. Every credit back to Reconciliation, whole.
        reason = "Deposit and first rent booked as the wrong month's rent — re-booked"
        for event in events:
            void_and_requeue_credit(event.payment, reason=reason)

        # 2. The first rent month, then the charges before it. Only a charge
        #    left with no money on it goes; anything else stops the repair.
        if fix.first_rent_month:
            tenant.first_rent_month = fix.first_rent_month
            tenant.save(update_fields=["first_rent_month", "updated_at"])
        first = tenant.first_rent_period
        for row in Arrears.objects.filter(tenant=tenant):
            if (row.period_year, row.period_month) >= first:
                continue
            if rent_payments_for(tenant, row.period_month, row.period_year).exists() \
                    or row.credit_applied or row.waived_amount:
                raise CommandError(
                    f"{fix.unit}: the {row.period_month}/{row.period_year} charge still has "
                    "money on it after the credits were returned. Resolve by hand."
                )
            row.delete()

        # 3. Each credit again, split as agreed, oldest first.
        for event, credit in zip(events, fix.credits, strict=True):
            event.refresh_from_db()
            assign_unmatched_credit(event_id=event.pk, tenant=tenant, deposit_amount=credit.deposit)

        tenant.refresh_from_db()
        self._report(tenant, "after")

        # 4. It must come out exactly as agreed, or none of it is kept.
        held = deposit_held_on_books(tenant)
        rows = {
            (r.period_year, r.period_month): (r.amount_paid, r.balance)
            for r in Arrears.objects.filter(tenant=tenant)
        }
        if held != fix.deposit_held or rows != fix.rent_rows:
            raise CommandError(
                f"{fix.unit}: result does not match — deposit {held:,.2f} "
                f"(expected {fix.deposit_held:,.2f}), charges {rows} (expected {fix.rent_rows})."
            )

        audit.record(
            actor=None,
            action="payment.rebook",
            object_type="tenant",
            object_id=tenant.pk,
            summary=(
                f"{fix.unit} {tenant.full_name}: {len(events)} bank credit(s) re-booked as "
                f"deposit {held:,.2f} + rent; first rent month "
                f"{first[1]}/{first[0]}; charges before it removed."
            ),
            new_values={"first_rent_month": str(tenant.first_rent_month or ""), "deposit_held": str(held)},
        )
