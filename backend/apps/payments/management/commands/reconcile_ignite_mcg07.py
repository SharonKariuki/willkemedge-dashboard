"""
Bring Ignite Access (MCG07) into line with the September 2026 statement.

Three separate faults stack up on this one account, and fixing any of them
alone moves the balance further from the truth rather than closer.

  1. THE DEPOSIT IS BOOKED AS RENT. Ignite paid 180,000 for the security
     deposit on 24 Aug 2026. It went in as a rent receipt, so it is being
     consumed by rent instead of held as a refundable liability, and it posted
     DR 1020 / CR 4120 + CR 2600 — recognising 155,172.41 of commercial rental
     income and declaring 24,827.59 of output VAT on money that has to be given
     back. Nothing offsets it: the "Rent Security Deposit" row on the issued
     statement was typed by hand, not stored, which is why the pair scan in
     ``repair_deposit_miscoding`` finds nothing here.

  2. AUGUST 2026 WAS BILLED AND SHOULD NOT HAVE BEEN. The tenancy runs from
     September — the issued statement raises September rent on 31 Aug and shows
     no August charge at all. The August row bills a month the tenant never
     occupied.

  3. OCTOBER 2026 WAS RAISED EARLY. Commercial lettings are billed a month
     ahead on the 25th, so October belongs to the 25 Sept run. It is already
     sitting on the account, dunning the tenant for a month not yet due.

Together they cancel out to something that looks nearly plausible — 28,800 due
where the statement says 69,600 — which is why this survived review:

    August rent + VAT        69,600
    September rent + VAT     69,600
    October rent + VAT       69,600
    less the 180,000        (180,000)
                            ────────
                              28,800     against a statement reading 69,600

Arrears carry no journal entries — the books are cash-basis and ``post_arrear``
is deliberately unwired (see ``ledger.posting``) — so removing a period is a
pure subledger operation with no ledger reversal to make. Only the deposit
reclassification touches the GL.

Safety
------
Preview is the DEFAULT. Nothing is written without ``--apply``. Every step
verifies the shape it expects and refuses rather than guessing: a period with
cash against it is never removed, and the payment must still be an unvoided
rent receipt for the expected amount.

Usage (Render Shell):
    python manage.py reconcile_ignite_mcg07
    python manage.py reconcile_ignite_mcg07 --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

ZERO = Decimal("0.00")

UNIT_LABEL = "MCG07"

#: The deposit, and the date it was received.
DEPOSIT_AMOUNT = Decimal("180000.00")

#: Periods billed that should not exist — (month, year, why).
DROP_PERIODS = [
    (8, 2026, "tenancy starts September; August was never occupied"),
    (10, 2026, "billed a month ahead on the 25th — October belongs to the 25 Sept run"),
]

#: What the account must read once the repair is done, as at 1 Sep 2026.
TARGET_TOTAL_DUE = Decimal("69600.00")


class Command(BaseCommand):
    help = "Reconcile Ignite Access (MCG07) to the September 2026 statement."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the repairs. Without this the command only previews them.",
        )

    def _periods_to_drop(self, tenant, *, ignore_pk, report: bool):
        """Arrears rows from DROP_PERIODS that carry no cash of their own.

        ``ignore_pk`` discounts the payment queued for reclassification — it is
        the 180,000 deposit sitting on August, and counting it would make the
        command refuse to remove the very row it exists to remove.
        """
        from django.db.models import Sum

        from apps.payments.models import Arrears
        from apps.payments.services import rent_payments_for

        rows = []
        for month, year, why in DROP_PERIODS:
            row = Arrears.objects.filter(
                tenant=tenant, period_month=month, period_year=year
            ).first()
            if row is None:
                if report:
                    self.stdout.write(f"  {month:>2}/{year}  already absent")
                continue

            paid = rent_payments_for(tenant, month, year)
            if ignore_pk is not None:
                paid = paid.exclude(pk=ignore_pk)
            paid = paid.aggregate(t=Sum("amount"))["t"] or ZERO

            # Cash against a period means somebody meant to pay it. Removing it
            # would strand the money, so it stops here for a human instead.
            if paid > ZERO:
                if report:
                    self.stdout.write(self.style.WARNING(
                        f"  {month:>2}/{year}  SKIPPED — carries {paid:,.2f} in payments"
                    ))
                continue

            if report:
                self.stdout.write(
                    f"  {month:>2}/{year}  remove  charge {row.expected_rent:,.2f} "
                    f"+ VAT {(row.expected_vat or ZERO):,.2f}  ({why})"
                )
            rows.append(row)
        return rows

    def handle(self, *args, **opts):
        import datetime as _dt

        from django.db.models import Sum

        from apps.payments.models import Payment, PaymentType
        from apps.payments.services import process_payment, void_payment
        from apps.payments.statement_service import build_statement
        from apps.tenants.models import Tenant

        apply_changes = opts["apply"]

        tenant = (
            Tenant.objects.select_related("unit", "unit__building")
            .filter(unit__label=UNIT_LABEL)
            .order_by("-id")
            .first()
        )
        if tenant is None:
            raise CommandError(f"No tenant found on unit {UNIT_LABEL}.")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{UNIT_LABEL} — {tenant} (tenant #{tenant.pk})"
        ))
        self.stdout.write(
            f"  move-in {tenant.move_in_date}   rent {tenant.monthly_rent:,.2f}   "
            f"deposit_paid {tenant.deposit_paid:,.2f}"
        )

        # --- 1. the deposit booked as rent ---------------------------------
        candidates = list(
            Payment.objects.filter(
                tenant=tenant,
                amount=DEPOSIT_AMOUNT,
                payment_type=PaymentType.RENT,
                voided_at__isnull=True,
            ).order_by("payment_date", "id")
        )
        if len(candidates) > 1:
            ids = ", ".join(str(p.pk) for p in candidates)
            raise CommandError(
                f"Ambiguous — {len(candidates)} unvoided rent payments of "
                f"{DEPOSIT_AMOUNT:,.2f} ({ids}). Resolve by hand."
            )
        deposit_payment = candidates[0] if candidates else None

        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Security deposit booked as rent"))
        if deposit_payment is None:
            already = Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True
            ).aggregate(t=Sum("amount"))["t"] or ZERO
            if already >= DEPOSIT_AMOUNT:
                self.stdout.write(f"  already re-booked — {already:,.2f} held as deposit")
            else:
                self.stdout.write(self.style.WARNING(
                    f"  no unvoided rent payment of {DEPOSIT_AMOUNT:,.2f} found"
                ))
        else:
            self.stdout.write(
                f"  payment #{deposit_payment.pk}  {deposit_payment.payment_date}  "
                f"KES {deposit_payment.amount:,.2f}  -> DEPOSIT (DR 1030 / CR 2100)"
            )

        # --- 2 & 3. periods that should not be billed ----------------------
        # The deposit is itself the cash sitting on August, so the periods can
        # only be judged once it is out of the way. In preview nothing has moved
        # yet, so its contribution is discounted explicitly; under --apply the
        # rows are re-read after the reclassification instead.
        ignore_pk = deposit_payment.pk if deposit_payment else None

        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Periods billed in error"))
        self._periods_to_drop(tenant, ignore_pk=ignore_pk, report=True)

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --apply to commit."
            ))
            return

        # --- write ----------------------------------------------------------
        with db_transaction.atomic():
            if deposit_payment is not None:
                amount = deposit_payment.amount
                date = deposit_payment.payment_date
                source, reference, pk = (
                    deposit_payment.source, deposit_payment.reference, deposit_payment.pk,
                )
                void_payment(
                    deposit_payment,
                    reason="Security deposit booked as rent — re-booked to 1030/2100",
                )
                process_payment(
                    tenant=tenant, amount=amount, payment_date=date,
                    period_month=date.month, period_year=date.year,
                    source=source, payment_type=PaymentType.DEPOSIT, reference=reference,
                    notes=f"Security deposit. Reclassified from rent payment #{pk}.",
                )

            # Re-read now the deposit is off the rent ledger: August's
            # `amount_paid` was that 180,000 and is nil again.
            for row in self._periods_to_drop(tenant, ignore_pk=None, report=False):
                row.delete()

            held = Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True
            ).aggregate(t=Sum("amount"))["t"] or ZERO
            tenant.deposit_paid = held
            tenant.save(update_fields=["deposit_paid", "updated_at"])

        # --- verify against the issued statement ----------------------------
        statement = build_statement(tenant, statement_date=_dt.date(2026, 9, 1))
        total = Decimal(statement["total_due"].replace(",", ""))

        self.stdout.write(self.style.MIGRATE_HEADING("\nResulting statement as at 1 Sep 2026"))
        self.stdout.write(f"  Arrears / Others   {statement['arrears_others']:>12}")
        self.stdout.write(f"  Current Month      {statement['current_month_rent']:>12}")
        self.stdout.write(f"  16% VAT on Rent    {statement['vat_on_rent']:>12}")
        self.stdout.write(f"  Total KES Due      {statement['total_due']:>12}")
        self.stdout.write(f"  Security Deposit   {statement['security_deposit']:>12}")
        for row in statement["rows"]:
            self.stdout.write(
                f"  {row['index']} {row['posting_date']:<20} {row['description']:<30} "
                f"{row['invoice_amount']:>12} {row['payment']:>12} {row['balance']:>10}"
            )

        if total != TARGET_TOTAL_DUE:
            raise CommandError(
                f"Total due is {total:,.2f}, expected {TARGET_TOTAL_DUE:,.2f}. "
                f"The account does not match the issued statement — investigate "
                f"before sending anything to the tenant."
            )
        self.stdout.write(self.style.SUCCESS(
            f"\nMatches the issued statement — {TARGET_TOTAL_DUE:,.2f} due, "
            f"{held:,.2f} held on deposit."
        ))
