"""
Bring Matasia Residential into line with the 21 Aug 2026 rent statement.

The commercial twin of this command is ``reconcile_matasia_commercial``; this
one repairs the residential half of the same building. Two differences matter:

  * Residential units carry NO VAT. Every ``expected_vat`` written here is 0.
  * The sheet's "Water + Other Costs" column is a real monthly charge that was
    never posted. MR202 is the worked example the owner raised: 1,800 of water
    on the statement, nothing in the system, so the tenant reads as owing 1,800
    less than she does and the water is never recovered.

Why the rent roll reads wrong today
-----------------------------------
Same root cause as commercial. The June 2026 cutover posted an ``opening_ar``
journal entry per tenant, but only for the tenancies that existed then, and it
put the figure in the GL rather than the arrears subledger. Matasia was loaded
in July and got neither, so no residential tenancy has a July arrears row: the
monthly rent roll starts its roll-forward at zero and every "B/Forward" shows
0.00.

That cuts both ways here. MR307 is carrying 6,000 forward and reads as settled.
MR306 is 20,000 in credit and reads as owing a full 22,000 — money the tenant
has already paid and is entitled to draw down.

How the opening position is seeded
----------------------------------
``build_monthly_ledger`` derives each month from ``Arrears`` (the charge),
``UtilityCharge`` (other costs) and ``Payment`` (cash) — it does NOT read
``Arrears.balance``. So a July row is created that nets to the statement's
B/Forward:

  * b/f owed (positive) — a July charge of that amount and no payment, so July
    closes owing exactly the brought-forward figure.
  * b/f in credit (negative) — no July charge plus an opening-credit payment of
    the absolute amount, so July closes negative and August draws it down. It
    has to be a Payment row rather than a negative balance: ``Arrears`` carries
    a ``balance >= 0`` check constraint, and the credit is real money the
    tenant is owed the use of.

Both are labelled with ``OPENING_MARKER`` so the roll reports them as brought
forward rather than as a month billed at that figure.

What this command does NOT do
-----------------------------
It never creates a payment to make a row balance. Step 4 rebuilds each August
row and compares it to the statement; a row that does not reconcile is
reported, because a shortfall there means cash is missing from the feed and
inventing it would hide the very thing worth knowing.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_matasia_residential
    python manage.py reconcile_matasia_residential --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.payments.monthly_ledger import OPENING_MARKER

JULY_CLOSE = _dt.date(2026, 7, 31)
AUG = (2026, 8)
JUL = (2026, 7)
OTHER_COSTS_LABEL = "Water + Other Costs"

# Marked so ``build_monthly_ledger`` reports the figure as brought forward
# rather than as a month billed at that amount.
OPENING_NOTE = (
    f"{OPENING_MARKER} from the 21 Aug 2026 statement's B/Forward column "
    "— not a billed month."
)


def D(value):
    return Decimal(str(value))


def _money(value):
    """Two decimal places, so a statement figure and a ledger one read alike."""
    return D(value).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# The 21 Aug 2026 statement, one row per live tenancy.
#
#   unit, tenant id, B/Forward July, August rent, water + other costs,
#   payment made, unpaid balance
#
# Rent is the sheet's "Aug-2026 Rent + Service Charge": the landlord's decision
# (recorded in reconcile_aug_2026) is that the service charge is folded into
# rent, so these agree with Tenant.monthly_rent. The last two columns are never
# written — they are what step 4 holds the rebuilt roll against.
#
# Tenant ids are checked against the unit label before anything is written —
# primary keys are not portable between databases.
#
# The five units the statement lists as vacant (MR201, MR203, MR303, MR305,
# MR308) have no tenancy and nothing to reconcile. MR204 is on the June sheet
# but absent from this statement; see VACANCY_QUERIES.
# ---------------------------------------------------------------------------
STATEMENT = [
    # unit,   tid,  b/f,        rent,     other,   paid,      unpaid
    ("MR202", 143, D(-2000), D(20000), D(1800), D(19800), D(0)),
    ("MR301", 144, D(1000), D(26000), D(600), D(27600), D(0)),
    ("MR302", 145, D(2000), D(20000), D(800), D(20800), D(2000)),
    ("MR304", 146, D(-8000), D(12000), D(4000), D(1000), D(7000)),
    ("MR306", 168, D(-20000), D(22000), D(0), D(0), D(2000)),
    ("MR307", 147, D(6000), D(22000), D(1000), D(23000), D(6000)),
]

# Units where the statement and the roster disagree. Reported, never
# auto-resolved — deciding whether a unit is let is the landlord's call.
VACANCY_QUERIES = [
    ("MR204", "on the June 2026 sheet at 12,000 but absent from the 21 Aug statement"),
]


class Command(BaseCommand):
    help = (
        "Reconcile Matasia Residential charges to the 21 Aug 2026 statement: seed "
        "each tenancy's July opening position, set August rent and post the "
        "water + other costs. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def _note(self, text):
        self.stdout.write(self.style.NOTICE(f"  note  {text}"))

    def handle(self, *args, **opts):
        self.apply = opts["apply"]
        self.changes = 0

        # -- pre-flight: every id must sit on the unit the statement names ----
        wrong = []
        for label, tid, *_ in STATEMENT:
            problem = self._resolve(tid, label)[1]
            if problem and "not found" not in problem:
                wrong.append(problem)
        if wrong:
            raise CommandError(
                "Pre-flight failed — tenant ids do not match their units:\n  "
                + "\n  ".join(wrong)
                + "\n\nPrimary keys are not portable between databases. Nothing was written."
            )

        self._head("1. July opening position (the statement's B/Forward)")
        for label, tid, bf, *_ in STATEMENT:
            self._step(tid, label, self._seed_opening, bf)

        self._head("2. August rent (residential — no VAT)")
        for label, tid, _bf, rent, *_ in STATEMENT:
            self._step(tid, label, self._set_august_charge, rent)

        self._head(f"3. August {OTHER_COSTS_LABEL.lower()}")
        for label, tid, _bf, _rent, other, *_ in STATEMENT:
            self._step(tid, label, self._set_other_charges, other)

        self._head("4. Does the rebuilt August row match the statement?")
        for label, tid, _bf, _rent, _other, paid, unpaid in STATEMENT:
            self._step(tid, label, self._verify_august, paid, unpaid)

        self._head("5. Vacancy disagreements — reported, not changed")
        self._report_vacancies()

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

    # -- plumbing -----------------------------------------------------------

    def _resolve(self, tid, label):
        """Return (tenant, problem). The id must sit on the unit the sheet names."""
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
        if tenant is None:
            return None, f"tenant #{tid} not found"
        actual = tenant.unit.label if tenant.unit else "(no unit)"
        if actual.upper() != label.upper():
            return None, f"#{tid} is '{tenant.full_name}' on {actual}, statement says {label}"
        return tenant, None

    def _step(self, tid, label, step, *args):
        tenant, problem = self._resolve(tid, label)
        if problem:
            self._skip(f"{label}: {problem}")
            return
        step(tenant, label, *args)

    # -- steps --------------------------------------------------------------

    def _seed_opening(self, tenant, label, bf):
        """Create the July row that carries the statement's B/Forward."""
        from apps.payments.models import Arrears, Payment, UtilityCharge
        from apps.payments.services import process_payment

        year, month = JUL
        if Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).exists():
            self._skip(f"{label} {tenant.full_name}: July row already exists — leaving it alone")
            return
        if bf == 0:
            self._skip(f"{label} {tenant.full_name}: nothing brought forward")
            return

        # The B/Forward is a closing position: it already contains every charge
        # raised up to that date. Seeding it alongside a charge that also sits in
        # the opening month counts that charge twice, and the error compounds
        # into every month after. MCG10 hit exactly this on the commercial side.
        clashing = UtilityCharge.objects.filter(
            tenant=tenant, period_year=year, period_month=month,
        )
        if clashing.exists():
            total = sum((c.amount for c in clashing), D(0))
            self._skip(
                f"{label} {tenant.full_name}: {month}/{year} already carries {total} of "
                f"charges, which the {bf} brought-forward would double-count — "
                f"clear them first, or fold them into the B/Forward"
            )
            return

        if bf > 0:
            self._do(f"{label} {tenant.full_name}: July closes owing {bf} (brought forward)")
            if self.apply:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=bf, expected_vat=D(0), amount_paid=D(0),
                    balance=bf, is_cleared=False, waive_notes=OPENING_NOTE,
                )
            return

        credit = -bf
        key = f"OPENING-CREDIT-2026-07-{label}"
        if Payment.objects.filter(tenant=tenant, idempotency_key=key).exists():
            self._skip(f"{label} {tenant.full_name}: opening credit already recorded")
            return
        self._do(f"{label} {tenant.full_name}: July closes {credit} in credit (brought forward)")
        if self.apply:
            with transaction.atomic():
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=D(0), expected_vat=D(0), amount_paid=D(0),
                    balance=D(0), is_cleared=True, waive_notes=OPENING_NOTE,
                )
                process_payment(
                    tenant=tenant, amount=credit, payment_date=JULY_CLOSE,
                    period_month=month, period_year=year, source="bank",
                    reference=key, idempotency_key=key,
                    notes=(
                        "Opening credit carried from the 21 Aug 2026 statement's "
                        "B/Forward column. Recorded as a prepayment because Arrears "
                        "cannot hold a negative balance; August draws it down."
                    ),
                )

    def _set_august_charge(self, tenant, label, rent):
        """Set August's obligation to the statement's rent. Residential: no VAT."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = AUG
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr and (arr.expected_rent, arr.expected_vat) == (rent, D(0)):
            self._skip(f"{label} {tenant.full_name}: already billed {rent}")
            return

        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{label} {tenant.full_name}: August {was} -> {rent}")
        if not self.apply:
            return
        with transaction.atomic():
            if arr:
                Arrears.objects.filter(pk=arr.pk).update(expected_rent=rent, expected_vat=D(0))
            else:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=rent, expected_vat=D(0), amount_paid=D(0),
                    balance=rent, is_cleared=False,
                )
            # Let the canonical routine re-derive amount_paid / balance / status.
            _update_arrears(tenant, month, year)

    def _set_other_charges(self, tenant, label, amount):
        """Post the statement's 'Water + Other Costs' column as a UtilityCharge."""
        from apps.payments.models import UtilityCharge

        year, month = AUG
        existing = UtilityCharge.objects.filter(
            tenant=tenant, period_year=year, period_month=month,
        )
        current = sum((u.amount for u in existing), D(0))
        if current == amount:
            self._skip(
                f"{label} {tenant.full_name}: "
                + (f"already {amount}" if amount else "no water or other costs")
            )
            return
        if existing.exists():
            self._skip(
                f"{label} {tenant.full_name}: has {current} of other charges but the "
                f"statement says {amount} — leaving it for review rather than overwriting"
            )
            return

        self._do(f"{label} {tenant.full_name}: August {OTHER_COSTS_LABEL.lower()} {amount}")
        if self.apply:
            UtilityCharge.objects.create(
                tenant=tenant, posting_date=_dt.date(2026, 8, 1),
                period_year=year, period_month=month,
                label=OTHER_COSTS_LABEL, amount=amount,
                notes="From the 21 Aug 2026 statement's 'Water + Other Costs' column.",
            )

    def _verify_august(self, tenant, label, paid, unpaid):
        """Rebuild the August row and hold it against the statement.

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
                    tenant, months=0, today=_dt.date(year, month, 21)
                )
                if (r["period_year"], r["period_month"]) == (year, month)
            ),
            None,
        )
        if row is None:
            self._skip(f"{label} {tenant.full_name}: no August row to check")
            return

        got_paid, got_balance = _money(row["paid"]), _money(row["balance"])
        paid, unpaid = _money(paid), _money(unpaid)
        if (got_paid, got_balance) == (paid, unpaid):
            self.stdout.write(f"  ok    {label} {tenant.full_name}: paid {paid}, owing {unpaid}")
            return

        detail = []
        if got_paid != paid:
            detail.append(f"paid {got_paid} vs statement {paid}")
        if got_balance != unpaid:
            detail.append(f"owing {got_balance} vs statement {unpaid}")
        self._note(
            f"{label} {tenant.full_name}: {'; '.join(detail)} "
            f"(b/f {row['brought_forward']} + rent {row['rent']} "
            f"+ other {row['other_charges']} = {row['total_due']})"
        )

    def _report_vacancies(self):
        from apps.buildings.models import Unit
        from apps.tenants.models import Tenant, TenantStatus

        for label, why in VACANCY_QUERIES:
            unit = Unit.objects.filter(label__iexact=label).first()
            if unit is None:
                self._skip(f"{label}: not in the database — may already be resolved")
                continue
            tenant = Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).first()
            who = tenant.full_name if tenant else "no active tenant"
            self._note(f"{label} ({who}): {why}")
