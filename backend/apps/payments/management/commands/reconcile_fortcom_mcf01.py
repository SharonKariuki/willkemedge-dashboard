"""
Reconcile Fortcom Realtors (MCF01) to the 1 Sept 2026 rent statement.

Fortcom moved into MCF01 on 10 August 2026 and paid 75,000 in one transfer.
That single credit is the whole of the story, and it has been read three
different ways:

  1. Ingestion read it as quarterly rent and split it 25,000 x August,
     September, October (``reconcile_aug_2026``). That raised charges for two
     months nobody had billed and left the tenancy looking settled to October.
  2. ``apply_matasia_answers`` corrected the split to 50,000 deposit + 25,000
     August rent, and dropped the two invented charges.
  3. The 1 Sept 2026 statement — the landlord's own document, and the first one
     issued after that correction — confirms the reading and adds what the books
     did not yet know: the 50,000 is a TWO-month deposit in full, not a part
     payment of the three-month commercial rule.

This command settles the tenancy against that statement. It is the deposit and
the September charge that still need work; the August position and the payment
split are checked, not rewritten, because they already belong to the two
commands above and this one must not fight them.

What the statement says
-----------------------
    #  Posting date   Description                Invoice  Payment    Balance
    1  10 Aug 2026    Payment Received                     75,000   (75,000)
    2  10 Aug 2026    Two Months Rent Deposit     50,000            (25,000)
    3  10 Aug 2026    Month Rent - August-2026    25,000                  0
    4  10 Aug 2026    16% VAT on Rent              4,000              4,000
    5  31 Aug 2026    Month Rent - Sept-2026      25,000             29,000
    6  31 Aug 2026    16% VAT on Rent              4,000             33,000

    Arrears / other costs   4,000      (August's VAT, unpaid)
    Current month rent     29,000      (September rent + VAT)
    Total balance due      33,000

Why 33,000 is also the rent-side balance
----------------------------------------
The statement runs the deposit through the same column as the rent. The books
do not: a deposit is a refundable liability (2100), it is not income, and
``rent_payments_for`` deliberately refuses to let it settle a rent period.

The two still agree, because the deposit invoice and the 50,000 of cash that
paid it cancel out. Strip both from the statement and what is left is 58,000
charged against 25,000 of rent received — 33,000, the same figure. So the
acceptance check is that the August and September ``Arrears`` balances sum to
the statement's total, with the deposit sitting outside them entirely.

The two months' deposit
-----------------------
``apps.tenants.deposits`` holds a commercial letting to three months' rent, so
Fortcom's 50,000 reads as 25,000 short and is reported as a shortfall by
``check_data_integrity`` and by the tenant API's deposit card. The statement
says otherwise: line 2 invoices "Two Months Rent Deposit" at 50,000 and the
running balance clears it, so the lease was agreed at two months and Fortcom
owes nothing further. That is what ``Tenant.agreed_deposit`` is for — the
agreement, where it differs from the rule — and setting it retires the phantom
25,000 without touching ``deposit_paid``, which records what was received.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_fortcom_mcf01
    python manage.py reconcile_fortcom_mcf01 --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def D(value):
    return Decimal(str(value))


UNIT = "MCF01"
TENANT_ID = 175
TENANT_NAME = "Fortcom Realtors Limited"

STATEMENT_DATE = _dt.date(2026, 9, 1)

RENT = D("25000.00")
VAT = D("4000.00")          # 16% of 25,000, per lines 4 and 6
AUG = (2026, 8)
SEP = (2026, 9)

# The bank credit the whole statement hangs on.
BANK_REF = "S48023247_10082026_2"
PAID_ON = _dt.date(2026, 8, 10)
BANKED = D("75000.00")

# Line 2. Two months' rent, agreed — not a part payment of the three-month rule.
DEPOSIT = D("50000.00")
DEPOSIT_MONTHS = 2
DEPOSIT_BASIS = (
    "Two months' rent, per line 2 of the 1 Sept 2026 statement. The commercial "
    "rule is three months; this letting was agreed at two and is paid in full."
)

# The statement's ledger, verbatim — (posting date, description, invoice, payment).
# Kept whole rather than reduced to the few figures the command writes, because
# it is the running balance that proves 33,000 and the tests foot against it.
LEDGER = [
    (PAID_ON, "Payment Received", D(0), BANKED),
    (PAID_ON, "Two Months Rent Deposit", DEPOSIT, D(0)),
    (PAID_ON, "Month Rent - August-2026", RENT, D(0)),
    (PAID_ON, "16% VAT on Rent", VAT, D(0)),
    (_dt.date(2026, 8, 31), "Month Rent - Sept-2026", RENT, D(0)),
    (_dt.date(2026, 8, 31), "16% VAT on Rent", VAT, D(0)),
]

# The summary box, which foots to the same total by a different route.
SUMMARY_ARREARS = D("4000.00")       # August's VAT, still unpaid
SUMMARY_CURRENT = D("29000.00")      # September rent + VAT
TOTAL_DUE = D("33000.00")

# What each period must close at for the books to reproduce the statement —
# (period, rent, VAT, closing balance).
# August: 29,000 charged, 25,000 of rent received, the VAT outstanding.
# September: charged on 31 Aug, nothing paid against it yet.
PERIODS = [
    (AUG, RENT, VAT, D("4000.00")),
    (SEP, RENT, VAT, D("29000.00")),
]


class Command(BaseCommand):
    help = (
        "Reconcile Fortcom Realtors (MCF01) to the 1 Sept 2026 statement: record "
        "the two-month deposit agreement and raise September's rent and VAT, then "
        "check the tenancy closes at 33,000. Dry-run unless --apply."
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

        tenant = self._preflight()

        self._head("1. The letting")
        self._check_letting(tenant)

        self._head("2. Rent security deposit")
        self._set_agreed_deposit(tenant)
        self._check_deposit_received(tenant)

        self._head("3. Rent charged")
        for period, rent, vat, _closing in PERIODS:
            self._set_charge(tenant, period, rent, vat)

        self._head("4. Does it foot to the statement?")
        self._foot(tenant)

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

    # -- pre-flight ---------------------------------------------------------

    def _preflight(self):
        """Primary keys are not portable between databases — prove the id first."""
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(pk=TENANT_ID).select_related("unit").first()
        if tenant is None:
            raise CommandError(
                f"Pre-flight failed — tenant #{TENANT_ID} ({TENANT_NAME}) not found. "
                f"Nothing was written."
            )
        actual = tenant.unit.label if tenant.unit else "(no unit)"
        if actual.upper() != UNIT:
            raise CommandError(
                f"Pre-flight failed — #{TENANT_ID} is '{tenant.full_name}' on {actual}, "
                f"the statement says {UNIT}. Primary keys are not portable between "
                f"databases. Nothing was written."
            )
        return tenant

    # -- steps --------------------------------------------------------------

    def _check_letting(self, tenant):
        """Rent and VAT are read, never written — the statement agrees with the roll.

        If they ever stop agreeing that is a change of terms, not a
        reconciliation, so it is reported and left alone.
        """
        from apps.payments.services import expected_vat_for

        if tenant.monthly_rent != RENT:
            self._skip(
                f"{UNIT} {tenant.full_name}: the roll says rent is {tenant.monthly_rent}, "
                f"the statement says {RENT} — a change of terms, not a reconciliation"
            )
            return
        derived = expected_vat_for(tenant, RENT)
        if derived != VAT:
            self._skip(
                f"{UNIT} {tenant.full_name}: VAT on {RENT} derives to {derived}, the "
                f"statement charges {VAT} — check the unit is still BUSINESS-classified"
            )
            return
        self.stdout.write(f"  {UNIT} {tenant.full_name}: {RENT} + {VAT} VAT a month")

    def _set_agreed_deposit(self, tenant):
        """Record the two-month agreement, so the three-month rule stops reporting
        a shortfall against money nobody owes."""
        from apps.tenants.deposits import deposit_shortfall, expected_deposit

        if tenant.agreed_deposit == DEPOSIT:
            self._skip(f"{UNIT}: deposit already agreed at {DEPOSIT} ({DEPOSIT_MONTHS} months)")
            return

        was = expected_deposit(tenant)
        shortfall = deposit_shortfall(tenant)
        self._do(
            f"{UNIT}: deposit held against {was} -> {DEPOSIT} "
            f"({DEPOSIT_MONTHS} x {RENT}), retiring a reported shortfall of {shortfall}"
        )
        if self.apply:
            tenant.agreed_deposit = DEPOSIT
            tenant.notes = (
                f"{tenant.notes}\nDeposit agreed at {DEPOSIT_MONTHS} months' rent "
                f"({DEPOSIT}): {DEPOSIT_BASIS}"
            ).strip()
            tenant.save(update_fields=["agreed_deposit", "notes", "updated_at"])

    def _check_deposit_received(self, tenant):
        """Reconcile ``deposit_paid`` to the deposit actually banked.

        The 50,000 is half of one bank credit, and cutting that credit into a
        deposit and a month's rent belongs to ``apply_matasia_answers``. If that
        split has not been made yet this reports it rather than doing it here:
        two commands allocating the same money is how it gets counted twice.
        """
        from apps.payments.models import Payment, PaymentType

        live = Payment.objects.filter(
            tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
        )
        banked = sum((p.amount for p in live), D(0))

        if banked != DEPOSIT:
            self._skip(
                f"{UNIT}: {banked} of deposit payments on record, the statement says "
                f"{DEPOSIT} — run apply_matasia_answers first, which splits the "
                f"{BANKED} banked under {BANK_REF}. Leaving deposit_paid alone."
            )
            return

        if tenant.deposit_paid == DEPOSIT:
            self._skip(f"{UNIT}: {DEPOSIT} received and recorded")
            return

        self._do(f"{UNIT}: deposit received {tenant.deposit_paid} -> {DEPOSIT}")
        if self.apply:
            tenant.deposit_paid = DEPOSIT
            tenant.save(update_fields=["deposit_paid", "updated_at"])

    def _set_charge(self, tenant, period, rent, vat):
        """Raise or correct one period's rent and VAT, then let the canonical
        routine re-derive what is paid and what is left."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = period
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr and (arr.expected_rent, arr.expected_vat) == (rent, vat):
            self._skip(f"{UNIT}: {month}/{year} already {rent} + {vat} VAT")
            return

        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{UNIT}: {month}/{year} {was} -> {rent} + {vat} VAT")
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
            _update_arrears(tenant, month, year)

    def _foot(self, tenant):
        """Print the statement back from the books and say whether it ties.

        In a dry run the periods have not been written, so a month this run
        would raise still reads as "not billed" — the gap it is there to close.
        """
        from apps.payments.models import Arrears

        self.stdout.write(f"      {'period':<10}{'charged':>12}{'paid':>12}{'balance':>12}")
        total = D(0)
        gaps = []
        for period, _rent, _vat, closing in PERIODS:
            year, month = period
            arr = Arrears.objects.filter(
                tenant=tenant, period_year=year, period_month=month
            ).first()
            if arr is None:
                self.stdout.write(
                    f"      {month:02d}/{year:<7}{'not billed':>12}{'':>12}{'':>12}"
                )
                gaps.append(f"{month}/{year} is not billed")
                continue
            charged = arr.expected_rent + arr.expected_vat
            self.stdout.write(
                f"      {month:02d}/{year:<7}{charged:>12,.2f}"
                f"{arr.amount_paid:>12,.2f}{arr.balance:>12,.2f}"
            )
            total += arr.balance
            if arr.balance != closing:
                gaps.append(f"{month}/{year} closes at {arr.balance}, statement says {closing}")

        self.stdout.write(f"      {'':<10}{'':>12}{'':>12}{'-' * 12:>12}")
        self.stdout.write(f"      {'total':<10}{'':>12}{'':>12}{total:>12,.2f}")
        self.stdout.write(
            f"      deposit held separately: {tenant.deposit_paid:,.2f} "
            f"(a 2100 liability, outside the rent balance)"
        )

        if gaps or total != TOTAL_DUE:
            detail = "; ".join(gaps) or f"the periods sum to {total}"
            when = "the books do not yet reproduce" if not self.apply else "does not reproduce"
            self._note(
                f"{when} the {STATEMENT_DATE:%d %b %Y} statement's "
                f"{TOTAL_DUE:,.2f} — {detail}"
            )
            if self.apply:
                raise CommandError(
                    f"Reconciliation did not foot to {TOTAL_DUE}. The changes above were "
                    f"written; investigate before relying on the rent roll for {UNIT}."
                )
            return

        self.stdout.write(self.style.SUCCESS(
            f"  reproduces the {STATEMENT_DATE:%d %b %Y} statement exactly: "
            f"{SUMMARY_ARREARS:,.2f} arrears + {SUMMARY_CURRENT:,.2f} current = "
            f"{TOTAL_DUE:,.2f} due"
        ))
