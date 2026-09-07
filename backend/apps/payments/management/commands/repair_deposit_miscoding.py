"""
Re-book security deposits that were recorded as rent and cancelled out by hand.

Background
----------
Until `allocate_payment_fifo` learned about payment types, every credit off the
Co-op feed was forced to `PaymentType.RENT`. There was no way to tell the system
"this 180,000 is a deposit", so the back office patched it on the statement
instead: leave the money booked as rent, then raise an equal `UtilityCharge`
labelled something like "Rent Security Deposit" to cancel it out of the balance.

The tenant's closing balance comes out right, which is why this survived. The
books do not. Ignite Access (KE) Limited, MCG07, 24 Aug 2026 — a commercial
letting, so the rent payment ran through the VAT-inclusive split:

    posted        DR 1020 Operating Bank            180,000.00
                     CR 4120 Commercial Rent Income            155,172.41
                     CR 2600 VAT Payable                        24,827.59
                  DR 1040 Accounts Receivable       180,000.00
                     CR 4150 Service Charge / Utils            180,000.00

    should be     DR 1030 Tenant Deposit Bank       180,000.00
                     CR 2100 Tenant Deposits Held              180,000.00

So: 335,172.41 of income that does not exist, 24,827.59 of output VAT declared
on money that has to be given back, a 180,000 receivable against nothing, and no
deposit liability on the balance sheet at all. `Tenant.deposit_paid` is untouched
too, so `deposit_shortfall` reports the tenant still owes the whole deposit.

What this does
--------------
For each miscoded pair it finds:

  1. voids the rent Payment      — posts the mirror reversal, re-derives arrears
  2. deletes the offsetting charge — posts its reversal (see
     `ledger.posting.reverse_utility_charge`, added with this repair; deleting a
     UtilityCharge used to leave its entry standing)
  3. records one Payment of type DEPOSIT for the same amount and date
     — DR 1030 / CR 2100, and excluded from the statement ledger, arrears,
     collection and income everywhere
  4. sets `Tenant.deposit_paid` to the deposit now held

Net cash movement is nil and the tenant's closing balance is unchanged. Only the
narration and the GL change.

Matching
--------
A pair is a `UtilityCharge` whose label mentions "deposit" plus a non-void
`PaymentType.RENT` Payment for the same tenant, the same amount, dated within
`--window` days of the charge. Anything ambiguous — no candidate, or more than
one — is reported and skipped rather than guessed at.

Safety
------
Preview is the DEFAULT. Nothing is written without ``--apply``.

Usage (Render Shell):
    python manage.py repair_deposit_miscoding                 # preview
    python manage.py repair_deposit_miscoding --unit MCG07    # scope to a unit
    python manage.py repair_deposit_miscoding --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

ZERO = Decimal("0.00")

#: A charge is a candidate if its label contains this (case-insensitive).
DEPOSIT_LABEL_HINT = "deposit"

#: Days either side of the charge's posting date to look for the paired payment.
DEFAULT_WINDOW_DAYS = 7


class Command(BaseCommand):
    help = "Re-book deposits recorded as rent + an offsetting charge as real deposits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the repairs. Without this the command only previews them.",
        )
        parser.add_argument(
            "--unit", type=str, default=None,
            help="Restrict to a single unit label, e.g. MCG07.",
        )
        parser.add_argument(
            "--tenant", type=int, default=None,
            help="Restrict to a single tenant id.",
        )
        parser.add_argument(
            "--window", type=int, default=DEFAULT_WINDOW_DAYS,
            help=f"Days either side of the charge to match the payment (default {DEFAULT_WINDOW_DAYS}).",
        )

    def handle(self, *args, **opts):
        import datetime as _dt

        from django.db.models import Sum

        from apps.payments.models import Payment, PaymentType, UtilityCharge
        from apps.payments.services import process_payment, void_payment

        apply_changes = opts["apply"]
        window = _dt.timedelta(days=opts["window"])

        charges = (
            UtilityCharge.objects.filter(label__icontains=DEPOSIT_LABEL_HINT)
            .select_related("tenant", "tenant__unit", "tenant__unit__building")
            .order_by("posting_date", "id")
        )
        if opts["unit"]:
            charges = charges.filter(tenant__unit__label=opts["unit"])
        if opts["tenant"]:
            charges = charges.filter(tenant_id=opts["tenant"])

        pairs, skipped = [], []

        for charge in charges:
            if charge.amount <= ZERO:
                skipped.append((charge, "charge is a credit note, not a deposit patch"))
                continue

            candidates = list(
                Payment.objects.filter(
                    tenant=charge.tenant,
                    amount=charge.amount,
                    payment_type=PaymentType.RENT,
                    voided_at__isnull=True,
                    payment_date__gte=charge.posting_date - window,
                    payment_date__lte=charge.posting_date + window,
                ).order_by("payment_date", "id")
            )
            if not candidates:
                skipped.append((charge, "no matching unvoided rent payment"))
                continue
            if len(candidates) > 1:
                ids = ", ".join(str(p.pk) for p in candidates)
                skipped.append((charge, f"ambiguous — {len(candidates)} candidate payments ({ids})"))
                continue

            pairs.append((charge, candidates[0]))

        self._report(pairs, skipped)

        if not pairs:
            self.stdout.write(self.style.WARNING("\nNothing to repair."))
            return

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN — nothing written. Re-run with --apply to commit "
                f"{len(pairs)} repair(s)."
            ))
            return

        for charge, payment in pairs:
            # Django clears `pk` on the instance after delete(), so capture
            # everything the audit trail needs to name while the rows exist.
            tenant = charge.tenant
            amount = payment.amount
            date = payment.payment_date
            reference = payment.reference
            payment_pk = payment.pk
            charge_pk = charge.pk

            with db_transaction.atomic():
                void_payment(
                    payment,
                    reason=f"Security deposit miscoded as rent — re-booked to 1030/2100 "
                           f"(offset charge #{charge_pk})",
                )
                charge.delete()

                deposit = process_payment(
                    tenant=tenant,
                    amount=amount,
                    payment_date=date,
                    period_month=date.month,
                    period_year=date.year,
                    source=payment.source,
                    payment_type=PaymentType.DEPOSIT,
                    reference=reference,
                    notes=f"Security deposit. Re-booked from rent payment #{payment_pk} "
                          f"and offsetting charge #{charge_pk}.",
                )

                # `deposit_paid` records what was actually received, so re-read
                # it from the deposit payments rather than adding to whatever
                # the field happened to hold.
                held = Payment.objects.filter(
                    tenant=tenant,
                    payment_type=PaymentType.DEPOSIT,
                    voided_at__isnull=True,
                ).aggregate(t=Sum("amount"))["t"] or ZERO
                tenant.deposit_paid = held
                tenant.save(update_fields=["deposit_paid", "updated_at"])

            self.stdout.write(self.style.SUCCESS(
                f"  repaired {tenant} ({self._unit(tenant)}): "
                f"payment #{payment_pk} voided, charge #{charge_pk} deleted, "
                f"deposit payment #{deposit.pk} created, deposit_paid = {held:,.2f}"
            ))

        self.stdout.write(self.style.SUCCESS(f"\nDone — {len(pairs)} repair(s) committed."))

    # -- reporting ----------------------------------------------------------

    def _unit(self, tenant) -> str:
        unit = getattr(tenant, "unit", None)
        return unit.label if unit else "no unit"

    def _report(self, pairs, skipped):
        self.stdout.write(self.style.MIGRATE_HEADING("\nDeposits miscoded as rent"))
        if not pairs:
            self.stdout.write("  (none found)")
        for charge, payment in pairs:
            tenant = charge.tenant
            self.stdout.write(
                f"  {self._unit(tenant):<10} {str(tenant)[:32]:<34} "
                f"KES {payment.amount:>12,.2f}  "
                f"payment #{payment.pk} ({payment.payment_date})  "
                f"+ charge #{charge.pk} \"{charge.label}\" ({charge.posting_date})"
            )

        if skipped:
            self.stdout.write(self.style.MIGRATE_HEADING("\nSkipped — needs a human"))
            for charge, why in skipped:
                self.stdout.write(
                    f"  {self._unit(charge.tenant):<10} charge #{charge.pk} "
                    f"\"{charge.label}\" KES {charge.amount:,.2f} — {why}"
                )
