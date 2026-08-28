"""
Bring Matasia Commercial into line with the 21 Aug 2026 rent statement.

This is the CHARGES side of the cleanup. The cash side — the two missing
payments, the MCG06 duplicate and the Fortcom quarterly split — lives in
``reconcile_aug_2026``. Both are idempotent, so either order works, but running
that one first makes this one's payment column reconcile.

Why the rent roll reads wrong today
-----------------------------------
Not one of the Matasia commercial tenancies has a July arrears row, so the
monthly rent roll starts its roll-forward at zero and every "Arrears b/f" shows
0.00. MCG01 is the worked example: the statement carries 12,000 forward, bills
24,000 + 3,840 VAT, and leaves 12,000 owing after a 27,840 payment. The app
shows b/f 0, total due 27,840, balance 0 — the tenant reads as settled while
owing 12,000, so they drop out of arrears reporting and never get dunned.

The June 2026 cutover posted an ``opening_ar`` journal entry per tenant, but
only for the 29 tenancies that existed then, and it put the figure in the GL
rather than the arrears subledger — which is why ``build_monthly_ledger`` cannot
see it either. Matasia was loaded in July and got neither.

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

Both are labelled in the notes so they are never mistaken for a billed month.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_matasia_commercial
    python manage.py reconcile_matasia_commercial --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

JULY_CLOSE = _dt.date(2026, 7, 31)
AUG = (2026, 8)
JUL = (2026, 7)


def D(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# The 21 Aug 2026 statement, one row per live tenancy.
#
#   unit, tenant id, B/Forward July, August rent, 16% VAT, other costs, label
#
# Tenant ids are checked against the unit label before anything is written —
# primary keys are not portable between databases.
# ---------------------------------------------------------------------------
STATEMENT = [
    # unit,   tid,  b/f,      rent,     vat,      other,   other label
    ("MCG01", 159, D(12000), D(24000), D(3840), D(0), ""),
    ("MCG02", 150, D(0), D(22500), D(0), D(0), ""),
    ("MCG03", 160, D(0), D(18000), D(2880), D(1360), "Other costs"),
    ("MCG05", 148, D(0), D(86500), D(13840), D(2440), "Other costs"),
    ("MCG10", 164, D(43800), D(25000), D(4000), D(12340), "Other costs"),
    ("MCF01", 175, D(0), D(25000), D(4000), D(0), ""),
    ("MCF03", 151, D(20000), D(22500), D(3600), D(0), ""),
    ("MCF12", 166, D(10000), D(50655), D(8105), D(0), ""),
    ("MCF13", 167, D(-27840), D(24000), D(3840), D(0), ""),
    ("MCF14", 152, D(-3900), D(22500), D(3600), D(0), ""),
]

# Units where the statement and the roster disagree about occupancy. Reported,
# never auto-resolved — deciding whether a unit is let is the landlord's call.
OCCUPANCY_QUERIES = [
    ("MCF04", 165, "statement says Vacant; the roster has Wilkem Ventures Co. Ltd. active at 25,000"),
    ("MCG07", 177, "statement says Vacant; Ignite Energy Access Ltd moved in after the statement was cut"),
]


class Command(BaseCommand):
    help = (
        "Reconcile Matasia Commercial charges to the 21 Aug 2026 statement: seed "
        "each tenancy's July opening position and set August rent, VAT and other "
        "costs. Dry-run unless --apply."
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
        from apps.tenants.models import Tenant

        self.apply = opts["apply"]
        self.changes = 0

        def resolve(tid, label):
            t = Tenant.objects.filter(pk=tid).select_related("unit").first()
            if t is None:
                return None, f"tenant #{tid} not found"
            actual = t.unit.label if t.unit else "(no unit)"
            if actual.upper() != label.upper():
                return None, f"#{tid} is '{t.full_name}' on {actual}, statement says {label}"
            return t, None

        # -- pre-flight: every id must sit on the unit the statement names ----
        wrong = []
        for label, tid, *_ in STATEMENT:
            _t, problem = resolve(tid, label)
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
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            self._seed_opening(t, label, bf)

        self._head("2. August rent and 16% VAT")
        for label, tid, _bf, rent, vat, *_ in STATEMENT:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            self._set_august_charge(t, label, rent, vat)

        self._head("3. August other costs / charges")
        for label, tid, _bf, _r, _v, other, other_label in STATEMENT:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            self._set_other_charges(t, label, other, other_label)

        self._head("4. Occupancy disagreements — reported, not changed")
        for label, tid, why in OCCUPANCY_QUERIES:
            t = Tenant.objects.filter(pk=tid).select_related("unit").first()
            if t is None or (t.unit and t.unit.label.upper() != label.upper()):
                self._skip(f"{label}: no matching tenant — may already be resolved")
                continue
            self._note(f"{label} {t.full_name}: {why}")

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nApplied {self.changes} change(s). The cash side (missing payments, the "
                f"MCG06 duplicate, the Fortcom split) is in reconcile_aug_2026."
            ))

    # -- steps --------------------------------------------------------------

    def _seed_opening(self, tenant, label, bf):
        """Create the July row that carries the statement's B/Forward."""
        from apps.payments.models import Arrears, Payment
        from apps.payments.services import process_payment

        year, month = JUL
        existing = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if existing:
            self._skip(f"{label} {tenant.full_name}: July row already exists — leaving it alone")
            return
        if bf == 0:
            self._skip(f"{label} {tenant.full_name}: nothing brought forward")
            return

        key = f"OPENING-CREDIT-2026-07-{label}"
        if bf > 0:
            self._do(f"{label} {tenant.full_name}: July closes owing {bf} (brought forward)")
            if self.apply:
                with transaction.atomic():
                    Arrears.objects.create(
                        tenant=tenant, period_year=year, period_month=month,
                        expected_rent=bf, expected_vat=D(0), amount_paid=D(0),
                        balance=bf, is_cleared=False,
                        waive_notes=(
                            "Opening position carried from the 21 Aug 2026 statement's "
                            "B/Forward column — not a billed month."
                        ),
                    )
            return

        credit = -bf
        if Payment.objects.filter(tenant=tenant, idempotency_key=key).exists():
            self._skip(f"{label} {tenant.full_name}: opening credit already recorded")
            return
        self._do(f"{label} {tenant.full_name}: July closes {credit} in credit (brought forward)")
        if self.apply:
            with transaction.atomic():
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=D(0), expected_vat=D(0), amount_paid=D(0),
                    balance=D(0), is_cleared=True,
                    waive_notes=(
                        "Opening position carried from the 21 Aug 2026 statement's "
                        "B/Forward column — not a billed month."
                    ),
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

    def _set_august_charge(self, tenant, label, rent, vat):
        """Set August's obligation to the statement's rent + VAT."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = AUG
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr and (arr.expected_rent, arr.expected_vat) == (rent, vat):
            self._skip(f"{label} {tenant.full_name}: already {rent} + {vat} VAT")
            return

        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{label} {tenant.full_name}: August {was} -> {rent} + {vat} VAT")
        if not self.apply:
            return
        with transaction.atomic():
            if arr:
                Arrears.objects.filter(pk=arr.pk).update(expected_rent=rent, expected_vat=vat)
            else:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=rent, expected_vat=vat, amount_paid=D(0),
                    balance=rent + vat, is_cleared=False,
                )
            # Let the canonical routine re-derive amount_paid / balance / status.
            _update_arrears(tenant, month, year)

    def _set_other_charges(self, tenant, label, amount, charge_label):
        """Post the statement's 'Other Costs/Charges' as a UtilityCharge."""
        from apps.payments.models import UtilityCharge

        year, month = AUG
        existing = UtilityCharge.objects.filter(
            tenant=tenant, period_year=year, period_month=month,
        )
        current = sum((u.amount for u in existing), D(0))
        if current == amount:
            self._skip(
                f"{label} {tenant.full_name}: "
                + (f"already {amount}" if amount else "no other costs")
            )
            return
        if existing.exists():
            self._skip(
                f"{label} {tenant.full_name}: has {current} of other charges but the "
                f"statement says {amount} — leaving it for review rather than overwriting"
            )
            return

        self._do(f"{label} {tenant.full_name}: August other costs {amount}")
        if self.apply:
            UtilityCharge.objects.create(
                tenant=tenant, posting_date=_dt.date(2026, 8, 1),
                period_year=year, period_month=month,
                label=charge_label or "Other costs", amount=amount,
                notes="From the 21 Aug 2026 statement's 'Other Costs/Charges' column.",
            )
