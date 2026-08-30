"""
Bring Donholm Nairobi into line with the 21 Aug 2026 outstanding-balances sheet.

The third of the property reconciliations, after ``reconcile_matasia_residential``
and ``reconcile_matasia_commercial``. Donholm differs from both in that its
tenancies pre-date the cutover, so the months before August are not empty — they
are populated and wrong, and the repair is a restatement rather than a seeding.

Why the rent roll reads wrong today
-----------------------------------
Three separate faults stack up on every Donholm row.

  1. THE CUTOVER ROW WAS OVERWRITTEN. June 2026 is the opening row: it carries
     the balance brought forward from the old books, not a month's rent. Until
     PR #152, ``_update_arrears`` recomputed ``expected_rent`` from
     ``tenant.monthly_rent`` on every payment, so the first payment against the
     cutover period restated the debt. All eight June rows now read a full
     month's rent instead of the figure the property roll loaded — Mercy
     Murunga's 7,450 opening reads 15,000.

  2. AUGUST WAS NEVER BILLED. ``generate_monthly_arrears`` has never run in
     production (the scheduled job failed at its guard clause for months). Six
     of the eight August rows exist only because an incoming payment created
     them ad hoc; DON1A and DON3B have no August row at all.

  3. CASH IS ALLOCATED TO THE WRONG MONTHS. The FIFO splitter applies a credit
     to the oldest open period, so cash received in August lands on June and
     July. The landlord's sheet does the opposite — it shows cash in the month
     it arrived and nets the older months into one "Arrears B/F" figure. The
     closing balance agrees either way, but every intermediate row disagrees,
     which is what makes the emailed statement and the landlord's sheet
     irreconcilable line by line.

Cash capture itself is sound: every payment the sheet reports for August is
already in the database, to the shilling. Nothing here invents or deletes money.

How the pre-August position is restated
---------------------------------------
``build_monthly_ledger`` derives each month from ``Arrears`` (the charge),
``UtilityCharge`` (other costs) and ``Payment`` (cash) — it does NOT read
``Arrears.balance``. So the whole pre-August history is collapsed onto the July
row, which is exactly what the sheet's "Arrears B/F July - 2026" column names:

  * every payment dated before August is allocated to July,
  * June is zeroed, its content folded forward,
  * July's charge is set to ``B/Forward + those payments``, so July closes
    owing precisely the sheet's B/Forward figure.

July is labelled with ``OPENING_MARKER`` so the roll reports it as brought
forward rather than as a month billed at that amount.

A B/Forward in credit (DON1B, DON3A) needs no special handling here: the cash
already sitting in those months exceeds the restated charge, so the roll-forward
carries the credit into August by itself. ``Arrears`` cannot hold a negative
balance, so step 5 draws the credit down through ``credit_applied`` — the same
routine ``generate_monthly_arrears`` uses when it raises a period — to keep the
stored balance, the dashboard and the arrears-reminder SMS from dunning a tenant
who is in hand.

What this command does NOT do
-----------------------------
It never creates a payment to make a row balance. Step 6 rebuilds each August
row and holds it against the sheet; a row that does not reconcile is reported,
because a shortfall there means cash is missing and inventing it would hide the
one thing worth knowing.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_donholm
    python manage.py reconcile_donholm --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.payments.monthly_ledger import OPENING_MARKER

STATEMENT_DATE = _dt.date(2026, 8, 21)
JULY_CLOSE = _dt.date(2026, 7, 31)
JUN = (2026, 6)
JUL = (2026, 7)
AUG = (2026, 8)
OTHER_COSTS_LABEL = "Water + Other Costs"

OPENING_NOTE = (
    f"{OPENING_MARKER} from the 21 Aug 2026 Donholm statement's "
    "'Arrears B/F July - 2026' column — not a billed month."
)


def D(value):
    return Decimal(str(value))


def _money(value):
    """Two decimal places, so a sheet figure and a ledger one read alike."""
    return D(value).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# "Donholm Nairobi - Outstanding Balances", 21 Aug 2026. One row per unit.
#
#   unit, tenant id, Arrears B/F July, August rent, other charges,
#   payment made, balance pending
#
# The last two columns are never written — they are what step 6 holds the
# rebuilt roll against.
#
# Tenant ids are checked against the unit label before anything is written:
# primary keys are not portable between databases, and a first pass of an
# earlier reconciliation matched the wrong person on a local copy.
#
# Two of the sheet's totals are a shilling out from its own columns (DON2B
# 6,150 + 20,000 - 2,096 = 24,054, printed 24,055; DON3B 34,445 + 20,000 +
# 2,623 = 57,068, printed 57,067). The components are what is posted, so the
# rebuilt balance lands a shilling under the printed one on those two rows.
# Recorded here rather than fudged, because the components are the figures the
# landlord's own water and rent records support.
# ---------------------------------------------------------------------------
STATEMENT = [
    # unit,   tid,        b/f,     rent,     other,      paid,     unpaid
    ("DON1A", 133,   D(7800), D(15000),  D(1500), D(16000),  D(8300)),
    ("DON1B", 134,   D(-900), D(20000),  D(2550), D(21650),      D(0)),
    ("DON2A", 135,   D(1050), D(20000),  D(1200), D(22500),   D(-250)),
    ("DON2B", 136,   D(6150), D(20000), D(-2096), D(20000),  D(4054)),
    ("DON3A", 137, D(-21400), D(20000),  D(1350),     D(0),    D(-50)),
    ("DON3B", 138,  D(34445), D(20000),  D(2623), D(20000), D(37068)),
    ("DON4A", 139,      D(0), D(20000),  D(1200), D(21200),      D(0)),
    ("DON4B", 140,      D(0), D(20000),  D(1050), D(21050),      D(0)),
]

# Rows the sheet cannot agree with, and why. Reported at the end so the
# divergence is stated rather than discovered.
#
# The sheet is a snapshot taken on 21 Aug. Zachary Bwonda paid 21,000 on 26
# August, five days after it was drawn, so his rebuilt August row shows that
# cash and the sheet shows none. Forcing the sheet's figure would delete a real
# payment; the difference is the sheet being out of date, not the ledger being
# wrong.
KNOWN_DIVERGENCE = {
    "DON3A": (
        "paid 21,000 on 26 Aug 2026, five days after the sheet was drawn — the "
        "rebuilt row is right and the sheet is stale"
    ),
}


class Command(BaseCommand):
    help = (
        "Reconcile Donholm Nairobi to the 21 Aug 2026 outstanding-balances "
        "sheet: allocate August cash to August, restate the pre-August position "
        "to the sheet's B/Forward, bill August rent and post the other charges. "
        "Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    # -- reporting ----------------------------------------------------------

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def _note(self, text):
        self.stdout.write(self.style.NOTICE(f"  note  {text}"))

    def _ok(self, text):
        self.stdout.write(f"  ok    {text}")

    # -- main ---------------------------------------------------------------

    def handle(self, *args, **opts):
        self.apply = opts["apply"]
        self.changes = 0
        self.unreconciled = 0

        # -- pre-flight: every id must sit on the unit the sheet names --------
        # Ids are not portable between databases. A single mismatch means this
        # is pointed somewhere it should not be, so abort with nothing written
        # rather than restating half a property against the wrong roster.
        wrong = []
        for label, tid, *_ in STATEMENT:
            problem = self._resolve(tid, label)[1]
            if problem and "not found" not in problem:
                wrong.append(problem)
        if wrong:
            raise CommandError(
                "Pre-flight failed — tenant ids do not match their units:\n  "
                + "\n  ".join(wrong)
                + "\n\nPrimary keys are not portable between databases. "
                "Nothing was written."
            )

        self._head("1. August cash -> the August period (the sheet's 'Payment made')")
        for label, tid, *_ in STATEMENT:
            self._step(tid, label, self._repoint_august_cash)

        self._head("2. Pre-August position -> the sheet's 'Arrears B/F July - 2026'")
        for label, tid, bf, *_ in STATEMENT:
            self._step(tid, label, self._restate_opening, bf)

        self._head("3. August rent (Donholm is residential — no VAT)")
        for label, tid, _bf, rent, *_ in STATEMENT:
            self._step(tid, label, self._set_august_charge, rent)

        self._head(f"4. August {OTHER_COSTS_LABEL.lower()}")
        for label, tid, _bf, _rent, other, *_ in STATEMENT:
            self._step(tid, label, self._set_other_charges, other)

        self._head("5. Draw down credit carried into August")
        for label, tid, *_ in STATEMENT:
            self._step(tid, label, self._draw_down_credit)

        self._head("6. Does the rebuilt August row match the sheet?")
        for label, tid, _bf, _rent, _other, paid, unpaid in STATEMENT:
            self._step(tid, label, self._verify_august, paid, unpaid)

        self._summarise()

    def _summarise(self):
        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. "
                f"Re-run with --apply."
            ))
            return
        self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))
        if self.unreconciled:
            self.stdout.write(self.style.WARNING(
                f"{self.unreconciled} row(s) still differ from the sheet — "
                f"see the notes above before reissuing statements."
            ))

    # -- plumbing -----------------------------------------------------------

    def _resolve(self, tid, label):
        """Return (tenant, problem). The id must sit on the unit the sheet names."""
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
        if tenant is None:
            return None, f"tenant #{tid} not found"
        actual = tenant.unit.label if tenant.unit else "(no unit)"
        if actual.upper() != label.upper():
            return None, f"#{tid} is '{tenant.full_name}' on {actual}, sheet says {label}"
        return tenant, None

    def _step(self, tid, label, step, *args):
        tenant, problem = self._resolve(tid, label)
        if problem:
            self._skip(f"{label}: {problem}")
            return
        step(tenant, label, *args)

    @staticmethod
    def _live_payments(tenant):
        """Cash that settles rent: non-void, deposits excluded."""
        from apps.payments.models import Payment, PaymentType

        return (
            Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
            .exclude(payment_type=PaymentType.DEPOSIT)
        )

    @staticmethod
    def _record_allocation_repair(payment, *, old_period, new_period, reason):
        """Make every exceptional historical payment re-allocation traceable.

        A reconciliation is the rare, reviewed exception to the normal rule
        that payment allocations are immutable. The receipt's amount, date and
        tenant are never changed; this log records the allocation correction
        that lets the arrears subledger agree with the authoritative snapshot.
        """
        from apps.accounts import audit

        audit.record(
            action="payment.reallocate",
            object_type="payment",
            object_id=payment.pk,
            summary=(
                f"Reallocated KES {payment.amount} for {payment.tenant} from "
                f"{old_period[1]}/{old_period[0]} to {new_period[1]}/{new_period[0]} "
                f"by Donholm 21 Aug 2026 reconciliation: {reason}"
            ),
            old_values={
                "period_month": old_period[1],
                "period_year": old_period[0],
                "payment_date": payment.payment_date,
                "amount": payment.amount,
                "tenant_id": payment.tenant_id,
            },
            new_values={
                "period_month": new_period[1],
                "period_year": new_period[0],
            },
        )

    # -- steps --------------------------------------------------------------

    def _repoint_august_cash(self, tenant, label):
        """Allocate every August-dated payment to the August period.

        The sheet reports cash in the month it arrived; the FIFO splitter books
        it against the oldest open period, which back-dated most of Donholm's
        August receipts into June and July. Re-pointing changes only the period
        a payment is allocated to — never its amount, date or tenant — so the
        cash record is untouched and the GL entry, which dates itself from
        ``payment_date``, moves only its memo.

        Derived from the payment dates rather than a hardcoded list, so it
        stays correct if the roster or the feed has moved since the sheet was
        drawn; step 6 then holds the result against the sheet's total.
        """
        from apps.payments.services import _update_arrears

        year, month = AUG
        misfiled = list(
            self._live_payments(tenant)
            .filter(payment_date__year=year, payment_date__month=month)
            .exclude(period_year=year, period_month=month)
            .order_by("payment_date", "pk")
        )
        if not misfiled:
            self._skip(f"{label} {tenant.full_name}: August cash already sits in August")
            return

        total = sum((p.amount for p in misfiled), D(0))
        detail = ", ".join(
            f"{p.amount} ({p.period_month}/{p.period_year})" for p in misfiled
        )
        self._do(
            f"{label} {tenant.full_name}: {total} of August cash -> 8/2026  [{detail}]"
        )
        if not self.apply:
            return

        touched = {AUG}
        with transaction.atomic():
            for pay in misfiled:
                old_period = (pay.period_year, pay.period_month)
                touched.add(old_period)
                pay.period_year, pay.period_month = year, month
                # The post_save signal re-posts the journal entry, which keys on
                # the payment and dates itself from payment_date — so only its
                # memo, which names the period, is restated.
                pay.save(update_fields=["period_year", "period_month"])
                self._record_allocation_repair(
                    pay,
                    old_period=old_period,
                    new_period=AUG,
                    reason="cash received during August must settle the August roll period",
                )
            for period_year, period_month in sorted(touched):
                _update_arrears(tenant, period_month, period_year)

    def _restate_opening(self, tenant, label, bf):
        """Collapse everything before August onto July, closing at the sheet's B/F.

        July's charge is set to ``B/Forward + the cash still allocated before
        August``, so July closes owing exactly the B/Forward figure. June is
        zeroed and its cash moved forward, so the single opening row carries
        the whole pre-cutover-plus-June-and-July position — which is what the
        sheet's one "Arrears B/F" column means.
        """
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        jul_year, jul_month = JUL

        # Cash allocated to any period before August, wherever it currently sits.
        earlier = list(
            self._live_payments(tenant)
            .filter(period_year__lte=jul_year)
            .exclude(period_year=jul_year, period_month__gt=jul_month)
            .order_by("payment_date", "pk")
        )
        carried = sum((p.amount for p in earlier), D(0))
        charge = _money(bf + carried)
        if charge < 0:
            # Cannot happen with the sheet as written; guarded because a
            # negative charge would be silently clamped and lose the credit.
            self._note(
                f"{label} {tenant.full_name}: B/Forward {bf} plus {carried} of "
                f"pre-August cash gives a negative charge — left alone"
            )
            self.unreconciled += 1
            return

        strays = [p for p in earlier if (p.period_year, p.period_month) != JUL]
        existing = Arrears.objects.filter(
            tenant=tenant, period_year=jul_year, period_month=jul_month
        ).first()
        already = (
            existing is not None
            and _money(existing.expected_rent) == charge
            and existing.expected_vat == 0
            and OPENING_MARKER in (existing.waive_notes or "")
            and not strays
        )
        if already:
            self._skip(
                f"{label} {tenant.full_name}: July already carries {charge}, "
                f"closing at the sheet's {bf}"
            )
            return

        was = f"{existing.expected_rent}" if existing else "no row"
        moved = f", {len(strays)} payment(s) folded forward" if strays else ""
        self._do(
            f"{label} {tenant.full_name}: July {was} -> {charge} "
            f"(b/f {bf} + {carried} carried{moved})"
        )
        if not self.apply:
            return

        with transaction.atomic():
            moved_from = set()
            for pay in strays:
                old_period = (pay.period_year, pay.period_month)
                moved_from.add(old_period)
                pay.period_year, pay.period_month = jul_year, jul_month
                pay.save(update_fields=["period_year", "period_month"])
                self._record_allocation_repair(
                    pay,
                    old_period=old_period,
                    new_period=JUL,
                    reason="pre-August opening position is represented by the July brought-forward row",
                )

            Arrears.objects.update_or_create(
                tenant=tenant, period_year=jul_year, period_month=jul_month,
                defaults={
                    "expected_rent": charge,
                    "expected_vat": D(0),
                    "waived_amount": D(0),
                    "credit_applied": D(0),
                    "waive_notes": OPENING_NOTE,
                    # balance has no model default and the row may be new;
                    # _update_arrears re-derives it from the cash below.
                    "amount_paid": D(0),
                    "balance": charge,
                    "is_cleared": False,
                },
            )
            _update_arrears(tenant, jul_month, jul_year)

            # Every month before July is now folded into it — in practice just
            # the June cutover row. Zero them rather than delete: the rows are
            # the audit trail of the opening-balance import.
            earlier_rows = (
                Arrears.objects.filter(tenant=tenant, period_year__lte=jul_year)
                .exclude(period_year=jul_year, period_month__gte=jul_month)
                .values_list("period_year", "period_month")
            )
            for stale_year, stale_month in sorted(set(earlier_rows) | moved_from):
                if (stale_year, stale_month) == JUL:
                    continue
                stale = Arrears.objects.filter(
                    tenant=tenant, period_year=stale_year, period_month=stale_month
                )
                if not stale.exists():
                    # A payment came from a month that was never billed; there
                    # is no row to zero, and _update_arrears would invent one at
                    # a full month's rent.
                    continue
                stale.update(
                    expected_rent=D(0), expected_vat=D(0), waived_amount=D(0),
                    credit_applied=D(0),
                    waive_notes=(
                        "Folded into the July opening position by "
                        "reconcile_donholm — see the 21 Aug 2026 sheet."
                    ),
                )
                _update_arrears(tenant, stale_month, stale_year)

    def _set_august_charge(self, tenant, label, rent):
        """Set August's obligation to the sheet's rent. Residential: no VAT."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = AUG
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr and (_money(arr.expected_rent), _money(arr.expected_vat)) == (_money(rent), D("0.00")):
            self._skip(f"{label} {tenant.full_name}: already billed {rent}")
            return

        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{label} {tenant.full_name}: August {was} -> {rent}")
        if not self.apply:
            return
        with transaction.atomic():
            Arrears.objects.update_or_create(
                tenant=tenant, period_year=year, period_month=month,
                defaults={
                    "expected_rent": rent,
                    "expected_vat": D(0),
                    # balance has no model default and the row may be new;
                    # _update_arrears re-derives it from the cash below.
                    "amount_paid": D(0),
                    "balance": rent,
                    "is_cleared": False,
                },
            )
            # Let the canonical routine re-derive amount_paid / balance / status.
            _update_arrears(tenant, month, year)

    def _set_other_charges(self, tenant, label, amount):
        """Post the sheet's 'Others Charges' column as a UtilityCharge.

        DON2B's figure is negative: the landlord is crediting the tenant, not
        billing her. It is posted as written — a credit note belongs on the
        statement in the column that caused it.
        """
        from apps.payments.models import UtilityCharge

        year, month = AUG
        existing = UtilityCharge.objects.filter(
            tenant=tenant, period_year=year, period_month=month,
        )
        current = sum((u.amount for u in existing), D(0))
        if existing.exists():
            if _money(current) == _money(amount):
                self._skip(f"{label} {tenant.full_name}: already {amount}")
            else:
                self._skip(
                    f"{label} {tenant.full_name}: has {current} of other charges but the "
                    f"sheet says {amount} — leaving it for review rather than overwriting"
                )
            return
        if amount == 0:
            self._skip(f"{label} {tenant.full_name}: no other charges")
            return

        kind = "credit" if amount < 0 else "charge"
        self._do(f"{label} {tenant.full_name}: August other {kind} {amount}")
        if self.apply:
            UtilityCharge.objects.create(
                tenant=tenant, posting_date=_dt.date(year, month, 1),
                period_year=year, period_month=month,
                label=OTHER_COSTS_LABEL, amount=amount,
                notes=(
                    "From the 21 Aug 2026 Donholm statement's "
                    "'Others Charges' column."
                ),
            )

    def _draw_down_credit(self, tenant, label):
        """Apply banked overpayment to the August row.

        ``Arrears`` cannot hold a negative balance, so a tenant carrying a
        credit reads as owing a full month unless it is drawn down — and the
        arrears-reminder SMS duns from that stored figure. This is the same
        routine ``generate_monthly_arrears`` runs when it raises a period.
        """
        from apps.payments.models import Arrears
        from apps.payments.services import apply_available_credit

        year, month = AUG
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr is None:
            self._skip(f"{label} {tenant.full_name}: no August row yet")
            return
        if not self.apply:
            self._note(f"{label} {tenant.full_name}: applied after --apply")
            return

        before = arr.credit_applied or D(0)
        arr = apply_available_credit(arr)
        drawn = (arr.credit_applied or D(0)) - before
        if drawn <= 0:
            self._skip(f"{label} {tenant.full_name}: no credit to draw down")
            return
        self._do(
            f"{label} {tenant.full_name}: {drawn} of credit applied to August "
            f"(balance now {arr.balance})"
        )

    def _verify_august(self, tenant, label, paid, unpaid):
        """Rebuild the August row and hold it against the sheet.

        A mismatch is almost always missing cash — the charges side is what this
        command writes, and it writes it from the same sheet. Report it; never
        post a payment to close the gap.
        """
        from apps.payments.monthly_ledger import build_monthly_ledger

        year, month = AUG
        if not self.apply:
            self._note(f"{label} {tenant.full_name}: checked after --apply")
            return

        row = next(
            (
                r
                for r in build_monthly_ledger(
                    tenant,
                    months=0,
                    today=STATEMENT_DATE,
                    as_of=STATEMENT_DATE,
                )
                if (r["period_year"], r["period_month"]) == (year, month)
            ),
            None,
        )
        if row is None:
            self._skip(f"{label} {tenant.full_name}: no August row to check")
            self.unreconciled += 1
            return

        got_paid, got_balance = _money(row["paid"]), _money(row["balance"])
        paid, unpaid = _money(paid), _money(unpaid)
        if (got_paid, got_balance) == (paid, unpaid):
            self._ok(f"{label} {tenant.full_name}: paid {paid}, owing {unpaid}")
            return

        detail = []
        if got_paid != paid:
            detail.append(f"paid {got_paid} vs sheet {paid}")
        if got_balance != unpaid:
            detail.append(f"owing {got_balance} vs sheet {unpaid}")
        why = KNOWN_DIVERGENCE.get(label.upper())
        if why:
            self._note(f"{label} {tenant.full_name}: {'; '.join(detail)} — {why}")
            return
        self._note(
            f"{label} {tenant.full_name}: {'; '.join(detail)} "
            f"(b/f {row['brought_forward']} + rent {row['rent']} "
            f"+ other {row['other_charges']} = {row['total_due']})"
        )
        self.unreconciled += 1
