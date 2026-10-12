"""
Undo the July rent the catch-up billing raised over a nil Matasia opening.

The 21 Aug 2026 statement is the opening record for Matasia, and its B/Forward
is the only pre-August position the books carry (see reconcile_matasia_commercial
and apply_matasia_answers). Where that B/Forward was nil the reconcile commands
wrote no July row at all — and an empty July is exactly what
``generate_monthly_arrears`` reads as a month it forgot to raise. On 12 Sept 2026
it raised a full July for MCG02, MCG03 and MCG05, and FIFO has since been paying
later receipts into it: 18,120 of Glow by Ellie's 3 Oct payment settled a July
the statement says was never owed, leaving October looking unpaid.

The seed is fixed so this cannot recur. This command restates the rows it left:

  * the July row becomes the nil opening it should have been — charge 0, VAT 0,
    marked as an opening position so it is never billed again;
  * cash already allocated to it is not moved or voided. Payments stay exactly as
    received (the statement and rent roll read them by date); the July row simply
    stops consuming them, so the surplus is drawn down against the tenant's
    oldest open months the same way any prepayment is.

Only arrears rows change. No Payment is written or voided and nothing posts to
the ledger — the books are cash basis and arrears carry no journal entries.

It refuses, and says why, wherever the July row is not purely the catch-up's:
a payment dated before August (cash someone recorded for July itself), a utility
charge or a waiver in July. Those need a decision, not a repair — MCG05 is one:
a 102,600 receipt dated 15 July sits against its July.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py repair_matasia_july_rebill
    python manage.py repair_matasia_july_rebill --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

JUL = (2026, 7)
AUGUST_FIRST = _dt.date(2026, 8, 1)
ZERO = Decimal("0.00")


def _nil_openings():
    """(label, tenant id) for every Matasia tenancy the statement opened at nil."""
    from . import reconcile_matasia_commercial as commercial
    from . import reconcile_matasia_residential as residential

    rows = []
    for table in (commercial.STATEMENT, residential.STATEMENT):
        for label, tid, bf, *_ in table:
            if bf == 0:
                rows.append((label, tid))
    return rows


class Command(BaseCommand):
    help = (
        "Restate a July the catch-up billing raised over a nil Matasia opening. "
        "Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **opts):
        from apps.tenants.models import Tenant

        apply = opts["apply"]
        targets = _nil_openings()

        # Primary keys are not portable between databases: every id must still
        # sit on the unit the statement names before anything is written.
        resolved, wrong = [], []
        for label, tid in targets:
            tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
            if tenant is None:
                wrong.append(f"tenant #{tid} ({label}) not found")
            elif (tenant.unit.label if tenant.unit else "").upper() != label.upper():
                actual = tenant.unit.label if tenant.unit else "(no unit)"
                wrong.append(f"#{tid} is '{tenant.full_name}' on {actual}, statement says {label}")
            else:
                resolved.append((label, tenant))
        if wrong:
            raise CommandError(
                "Pre-flight failed — tenant ids do not match their units:\n  "
                + "\n  ".join(wrong)
                + "\n\nNothing was written."
            )

        repaired = held = 0
        for label, tenant in resolved:
            outcome = self._repair(label, tenant, apply)
            repaired += outcome == "repaired"
            held += outcome == "held"

        if not apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {repaired} July row(s) would be restated, {held} held for a "
                f"decision. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nRestated {repaired} July row(s); {held} held for a decision."
            ))

    def _repair(self, label, tenant, apply) -> str:
        from apps.payments.models import Arrears, Payment, PaymentType, UtilityCharge
        from apps.payments.monthly_ledger import OPENING_MARKER

        name = f"{label} {tenant.full_name}"
        year, month = JUL
        jul = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if jul is None:
            self.stdout.write(f"  ok    {name}: no July charge — nothing to restate")
            return "skipped"
        if OPENING_MARKER in (jul.waive_notes or ""):
            self.stdout.write(f"  ok    {name}: July is already the nil opening")
            return "skipped"

        reasons = []
        early = Payment.objects.filter(
            tenant=tenant, voided_at__isnull=True, payment_date__lt=AUGUST_FIRST,
        ).exclude(payment_type=PaymentType.DEPOSIT)
        if early.exists():
            listed = ", ".join(
                f"{p.amount} on {p.payment_date} ({p.reference or 'no reference'})" for p in early
            )
            reasons.append(f"payments dated before August: {listed}")
        charges = UtilityCharge.objects.filter(tenant=tenant, period_year=year, period_month=month)
        if charges.exists():
            reasons.append(f"July carries {sum((c.amount for c in charges), ZERO)} of other charges")
        if jul.waived_amount:
            reasons.append(f"July has {jul.waived_amount} waived")
        if reasons:
            self.stdout.write(self.style.NOTICE(
                f"  HOLD  {name}: July billed {jul.expected_rent} + {jul.expected_vat} VAT, but "
                + "; ".join(reasons)
                + " — needs a decision, not a repair"
            ))
            return "held"

        self.stdout.write(
            f"  fix   {name}: July {jul.expected_rent} + {jul.expected_vat} VAT (raised "
            f"{jul.created_at:%d %b %Y}) -> nil opening; {jul.amount_paid} already paid "
            f"into it goes to the oldest open month"
        )
        if apply:
            self._restate(tenant, jul)
        return "repaired"

    @transaction.atomic
    def _restate(self, tenant, jul):
        from apps.accounts import audit
        from apps.payments.models import Arrears
        from apps.payments.services import apply_available_credit

        jul = Arrears.objects.select_for_update().get(pk=jul.pk)
        old = {
            "expected_rent": str(jul.expected_rent),
            "expected_vat": str(jul.expected_vat),
            "credit_applied": str(jul.credit_applied),
            "balance": str(jul.balance),
        }
        jul.expected_rent = ZERO
        jul.expected_vat = ZERO
        # Credit drawn into a month that owes nothing goes back to the pool.
        jul.credit_applied = ZERO
        jul.balance = ZERO
        jul.is_cleared = True
        jul.waive_notes = (
            "Opening position carried from the 21 Aug 2026 statement's B/Forward "
            "column — not a billed month. Nil brought forward; the "
            f"{old['expected_rent']} + {old['expected_vat']} VAT the catch-up billing "
            f"raised on {jul.created_at:%d %b %Y} was restated by repair_matasia_july_rebill."
        )
        jul.save(update_fields=[
            "expected_rent", "expected_vat", "credit_applied", "balance",
            "is_cleared", "waive_notes", "updated_at",
        ])

        # Oldest first, the order the billing run draws credit down in.
        open_rows = (
            Arrears.objects.filter(tenant=tenant, balance__gt=0)
            .order_by("period_year", "period_month")
        )
        for row in open_rows:
            apply_available_credit(row)

        audit.record(
            action="arrears.restate_opening",
            object_type="arrears",
            object_id=jul.pk,
            object_label=f"{tenant.unit.label} July 2026",
            summary=(
                f"July 2026 for {tenant} restated to the nil opening the 21 Aug 2026 "
                f"statement carries; it had been billed by the catch-up run."
            ),
            old_values=old,
            new_values={
                "expected_rent": "0.00", "expected_vat": "0.00",
                "credit_applied": "0.00", "balance": "0.00",
            },
        )
